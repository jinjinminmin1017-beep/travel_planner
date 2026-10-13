"""Offline fixture benchmark: temporary SQLite/checkpoints, with no provider network calls."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

import app.services.rail_timetable_store as store_module  # noqa: E402
from app.data_sources.rail_12306_timetable_provider import (  # noqa: E402
    DiscoveryDiagnostics,
    DiscoveredRailService,
)
from app.services.rail_timetable_store import (  # noqa: E402
    RailServiceInput,
    RailStopTimeInput,
    RailTimetableBatch,
    RailTimetableStore,
)
from scripts.import_12306_timetable import _import_date  # noqa: E402
from scripts.rail_timetable_checkpoint import CheckpointDocument  # noqa: E402


def _discovery_state(items: Sequence[DiscoveredRailService]) -> dict[str, Any]:
    return {
        "version": 1,
        "service_date": items[0].service_date.isoformat(),
        "requested_prefixes": ["G", "D", "C"],
        "pending_prefixes": [],
        "services": {
            item.train_no_internal: {key: value for key, value in asdict(item).items() if key != "service_date"}
            for item in items
        },
        "query_count": 1,
        "split_prefix_count": 0,
        "response_hashes": ["offline-fixture-discovery"],
        "status": "COMPLETE",
    }


class OfflineFixtureProvider:
    """Implements the importer's provider interface without constructing an HTTP client."""

    def __init__(self, service_count: int, stop_count: int) -> None:
        self.service_count = service_count
        self.stop_count = stop_count
        self.detail_calls = 0
        self.discovery_calls = 0

    def items(self, service_date: date) -> list[DiscoveredRailService]:
        return [
            DiscoveredRailService(
                service_date=service_date,
                train_no_internal=f"fixture_{index:06d}",
                train_number=f"G{index}",
                origin_station_name="Fixture origin",
                destination_station_name="Fixture destination",
                total_stop_count=self.stop_count,
                summary_fingerprint=hashlib.sha256(f"{service_date}:{index}".encode()).hexdigest(),
            )
            for index in range(1, self.service_count + 1)
        ]

    def discover_services(
        self,
        service_date: date,
        *,
        resume_state: dict[str, Any],
        checkpoint_callback: Callable[[], None],
        **_kwargs: Any,
    ) -> tuple[list[DiscoveredRailService], DiscoveryDiagnostics]:
        self.discovery_calls += 1
        items = self.items(service_date)
        resume_state.update(_discovery_state(items))
        checkpoint_callback()
        return items, DiscoveryDiagnostics(1, 0, len(items), ("offline-fixture-discovery",))

    def fetch_complete_service(self, item: DiscoveredRailService) -> RailServiceInput:
        self.detail_calls += 1
        stops = []
        for index in range(self.stop_count):
            clock = (datetime(2026, 1, 1, 8) + timedelta(minutes=index * 10)).strftime("%H:%M")
            stops.append(
                RailStopTimeInput(
                    stop_sequence=index + 1,
                    station_code=f"FIX{index:03d}",
                    arrival_time=clock if index else None,
                    arrival_day_offset=0,
                    departure_time=clock if index < self.stop_count - 1 else None,
                    departure_day_offset=0,
                )
            )
        return RailServiceInput(
            service_date=item.service_date,
            train_no_internal=item.train_no_internal,
            train_number=item.train_number,
            origin_station_code=stops[0].station_code,
            destination_station_code=stops[-1].station_code,
            summary_fingerprint=item.summary_fingerprint,
            fetched_at=datetime.now(timezone.utc),
            stops=tuple(stops),
        )

    @property
    def request_metrics(self) -> dict[str, int | float]:
        return {"requests": 0, "discovery_requests": 0, "detail_requests": 0, "network_seconds": 0.0}

    def metrics_snapshot(self) -> dict[str, int | float]:
        return self.request_metrics


def _legacy_projection(
    payload: dict[str, Any], date_key: str, completed_train_nos: Sequence[str]
) -> dict[str, Any]:
    """Calculate every legacy detail save's JSON bytes from one final serialization.

    The discovered catalogs and historical dates stay constant. Only the current
    date's completed list grows; old indent=2 formatting gives its exact delta.
    Discovery, initial and final extra saves are excluded from this comparison.
    """
    state = payload["dates"][date_key]
    state["completed_train_nos"] = list(completed_train_nos)
    started = time.perf_counter()
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    serialization_seconds = time.perf_counter() - started
    count = len(completed_train_nos)
    deltas = [
        len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + (16 if index == 0 else 10)
        for index, value in enumerate(completed_train_nos)
    ]
    fixed_bytes = len(serialized) - sum(deltas)
    logical_bytes = count * fixed_bytes + sum(delta * (count - index) for index, delta in enumerate(deltas))
    return {
        "method": "one_measured_final_serialization_plus_exact_completed_list_growth",
        "physical_checkpoint_writes": 0,
        "measured_final_serialization_bytes": len(serialized),
        "measured_final_serialization_seconds": round(serialization_seconds, 6),
        "projected_per_service_write_count": count,
        "projected_logical_checkpoint_bytes": logical_bytes,
        "excluded_writes": "discovery callbacks, batch start, and final activation saves",
    }


class _ProfiledStore(RailTimetableStore):
    def __init__(self, path: Path) -> None:
        self.sql_phase = "other"
        super().__init__(path)

    def upsert_services(self, batch_id: str, services: Sequence[RailServiceInput]) -> list[str]:
        self.sql_phase = "upsert"
        try:
            return super().upsert_services(batch_id, services)
        finally:
            self.sql_phase = "other"

    def copy_services(self, source_batch_id: str, target_batch_id: str, train_nos_internal: Sequence[str]) -> set[str]:
        self.sql_phase = "copy"
        try:
            return super().copy_services(source_batch_id, target_batch_id, train_nos_internal)
        finally:
            self.sql_phase = "other"

    def activate_batch(self, batch_id: str) -> RailTimetableBatch:
        self.sql_phase = "activation"
        try:
            return super().activate_batch(batch_id)
        finally:
            self.sql_phase = "other"


@contextmanager
def _sql_profile(store: _ProfiledStore) -> Iterator[dict[str, dict[str, int]]]:
    original = store_module._connect
    stats: dict[str, dict[str, int]] = {}
    connections: list[sqlite3.Connection] = []

    def trace(sql: str) -> None:
        normalized = " ".join(sql.upper().split())
        phase = stats.setdefault(store.sql_phase, {"begin": 0, "commit": 0, "rollback": 0, "count_statements": 0})
        phase["begin"] += int(normalized.startswith("BEGIN"))
        phase["commit"] += int(normalized == "COMMIT")
        phase["rollback"] += int(normalized == "ROLLBACK")
        phase["count_statements"] += int("COUNT(" in normalized)

    def traced_connect(path: Path) -> sqlite3.Connection:
        conn = original(path)
        conn.set_trace_callback(trace)
        connections.append(conn)
        return conn

    store_module._connect = traced_connect
    try:
        yield stats
    finally:
        store_module._connect = original
        for conn in connections:
            conn.close()


def run_benchmark(
    *,
    services: int = 1000,
    historical_dates: int = 15,
    stops: int = 8,
    checkpoint_every: int = 100,
    storage_batch_size: int = 50,
    request_interval_seconds: float = 1.5,
    horizon_days: int = 15,
) -> dict[str, Any]:
    if not 1 <= services <= 20000 or not 0 <= historical_dates <= 90 or services * (historical_dates + 1) > 200000:
        raise ValueError("fixture capacity is limited to 200,000 total catalog entries")
    if not 2 <= stops <= 60 or checkpoint_every < 1 or storage_batch_size < 1:
        raise ValueError("stops must be 2..60 and write batch sizes must be positive")
    if request_interval_seconds < 1 or horizon_days < 1:
        raise ValueError("request interval must be at least 1 second and horizon days positive")
    current_date = date(2026, 10, 13)
    date_key = current_date.isoformat()
    provider = OfflineFixtureProvider(services, stops)
    legacy_dates: dict[str, Any] = {}
    with TemporaryDirectory(prefix="rail-import-benchmark-") as temporary:
        directory = Path(temporary)
        checkpoint_path = directory / "checkpoint.v2.json"
        document = CheckpointDocument(checkpoint_path, resume=False)
        for offset in range(historical_dates, 0, -1):
            historical_date = current_date - timedelta(days=offset)
            key = historical_date.isoformat()
            items = provider.items(historical_date)
            state = {
                "batch_id": f"fixture_{key}",
                "generation": key,
                "status": "ACTIVE",
                "service_count": services,
                "stop_count": services * stops,
                "discovery": _discovery_state(items),
            }
            document.date_state(key).update(state)
            document.save_date(key)
            legacy_dates[key] = {**state, "completed_train_nos": [item.train_no_internal for item in items]}
        seed_bytes = document.bytes_written
        seed_writes = document.write_count
        document.save_manifest()
        document = CheckpointDocument(checkpoint_path, resume=True)
        current_items = provider.items(current_date)
        legacy_dates[date_key] = {
            "batch_id": f"fixture_{date_key}",
            "status": "STAGING",
            "discovery": _discovery_state(current_items),
        }
        legacy = _legacy_projection(
            {"version": 1, "dates": legacy_dates}, date_key, [item.train_no_internal for item in current_items]
        )
        store = _ProfiledStore(directory / "rail.sqlite3")
        started = time.perf_counter()
        with _sql_profile(store) as sql_stats:
            summary = _import_date(
                service_date=current_date,
                provider=provider,
                store=store,
                checkpoint=document,
                checkpoint_path=checkpoint_path,
                resume=True,
                dry_run=False,
                train_numbers=(),
                prefixes=("G", "D", "C"),
                max_discovery_queries=None,
                max_trains=None,
                refresh=False,
                generation=date_key,
                checkpoint_every=checkpoint_every,
                checkpoint_interval=3600.0,
                storage_batch_size=storage_batch_size,
            )
        elapsed = time.perf_counter() - started
        actual_bytes = document.bytes_written
        new_result = {
            "elapsed_seconds": round(elapsed, 6),
            "physical_checkpoint_bytes": actual_bytes,
            "physical_checkpoint_writes": document.write_count,
            "checkpoint_write_seconds": round(document.write_seconds, 6),
            "historical_seed_bytes_excluded": seed_bytes,
            "historical_seed_writes_excluded": seed_writes,
            "pipeline_summary": summary,
            "sql_by_phase": sql_stats,
            "fixture_detail_calls": provider.detail_calls,
            "fixture_discovery_calls": provider.discovery_calls,
            "actual_network_requests": 0,
        }
        # Close any schema-initialization connections collected by sqlite's GC
        # before Windows removes the temporary directory.
        gc.collect()
    return {
        "benchmark_kind": "offline_fixture_capacity",
        "measurement_scope": "local JSON, SQLite, and importer orchestration; no real network throughput measured",
        "fixture": {
            "services_per_date": services,
            "historical_dates": historical_dates,
            "stops_per_service": stops,
            "checkpoint_every_services": checkpoint_every,
            "storage_batch_size": storage_batch_size,
        },
        "legacy_full_document_per_service": legacy,
        "current_date_files_periodic_writes": new_result,
        "logical_byte_reduction_factor": round(legacy["projected_logical_checkpoint_bytes"] / actual_bytes, 2) if actual_bytes else None,
        "network_spacing_estimate": {
            "request_interval_seconds": request_interval_seconds,
            "one_full_date_detail_seconds": services * request_interval_seconds,
            "full_window_detail_seconds": services * horizon_days * request_interval_seconds,
            "horizon_days": horizon_days,
            "formula": "services_per_date * dates * request_interval_seconds",
            "assumptions": "one detail request per service after discovery; excludes latency, discovery spacing, retries and reuse",
        },
        "temporary_files_removed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", type=int, default=1000)
    parser.add_argument("--historical-dates", type=int, default=15)
    parser.add_argument("--stops", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=100)
    parser.add_argument("--storage-batch-size", type=int, default=50)
    parser.add_argument("--request-interval-seconds", type=float, default=1.5)
    parser.add_argument("--horizon-days", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_benchmark(
            services=args.services,
            historical_dates=args.historical_dates,
            stops=args.stops,
            checkpoint_every=args.checkpoint_every,
            storage_batch_size=args.storage_batch_size,
            request_interval_seconds=args.request_interval_seconds,
            horizon_days=args.horizon_days,
        )
    except ValueError as exc:
        parser.error(str(exc))
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
