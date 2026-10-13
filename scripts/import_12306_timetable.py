from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))

from app.data_sources.config_loader import (  # noqa: E402
    RailTimetableSettings,
    load_project_env,
    load_rail_timetable_settings,
)
from app.data_sources.rail_12306_timetable_provider import (  # noqa: E402
    Rail12306TimetableProvider,
    DiscoveredRailService,
    RailTimetableAccessControlError,
    RailTimetableAmbiguousStopsError,
    RailTimetableBudgetExceeded,
    RailTimetableProviderError,
    RailTimetableServiceWithdrawnError,
    RailTimetableTemporaryError,
    RailTimetableUnsupportedStationError,
    SOURCE_VERSION,
)
from app.services.rail_timetable_store import RailServiceInput, RailTimetableStore, RailTimetableStoreError  # noqa: E402
from scripts.rail_timetable_checkpoint import (  # noqa: E402
    CheckpointDocument,
    RailCheckpointBusyError,
    RailCheckpointError,
    atomic_write_json,
    checkpoint_lock,
)


DEFAULT_CHECKPOINT = ROOT / "logs" / "rail_timetable_import_checkpoint.json"
EXIT_FAILED = 1
EXIT_ACCESS_CONTROL = 2
EXIT_TRANSIENT_FAILURE = 3
EXIT_BUDGET_EXHAUSTED = 4
EXIT_ALREADY_RUNNING = 5
logger = logging.getLogger("app.rail_timetable_import")
SHANGHAI = timezone(timedelta(hours=8))


class ImportBudget:
    def __init__(self, *, run_deadline: float | None = None, date_seconds: float = 0) -> None:
        self.run_deadline = run_deadline
        self.date_deadline = time.monotonic() + date_seconds if date_seconds else None

    def remaining(self) -> float | None:
        deadlines = [value for value in (self.run_deadline, self.date_deadline) if value is not None]
        return max(0.0, min(deadlines) - time.monotonic()) if deadlines else None

    def check(self) -> None:
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise RailTimetableBudgetExceeded("timetable import time budget exhausted")


class CheckpointCadence:
    def __init__(self, save: Callable[[], None], *, every: int, interval: float) -> None:
        self.save = save
        self.every = every
        self.interval = interval
        self.units = 0
        self.last_saved = time.monotonic()

    def tick(self, *, force: bool = False) -> None:
        self.units += 1
        if force or self.units >= self.every or time.monotonic() - self.last_saved >= self.interval:
            self.save()
            self.units = 0
            self.last_saved = time.monotonic()


def main() -> int:
    load_project_env(ROOT / ".env")
    settings = load_rail_timetable_settings()
    parser = argparse.ArgumentParser(
        description="Import current G/D/C timetable snapshots with low-frequency, resumable 12306 requests."
    )
    parser.add_argument("--mode", choices=("bootstrap", "refresh"), default="bootstrap")
    parser.add_argument("--date-from", type=date.fromisoformat, default=datetime.now(SHANGHAI).date())
    parser.add_argument("--days", type=int, default=settings.horizon_days)
    parser.add_argument("--interval-seconds", type=float, default=settings.import_interval_seconds)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--auto-resume-transient", action="store_true")
    parser.add_argument("--max-transient-resumes", type=int, default=6)
    parser.add_argument("--transient-resume-base-seconds", type=float, default=300.0)
    parser.add_argument("--transient-resume-max-seconds", type=float, default=3600.0)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--train-number", action="append", default=[])
    parser.add_argument("--prefix", action="append", default=[])
    parser.add_argument("--max-discovery-queries", type=int)
    parser.add_argument("--max-trains", type=int)
    parser.add_argument("--max-run-seconds", type=float, default=0, help="Whole process budget, including automatic resume waits; 0 is unlimited.")
    parser.add_argument("--max-date-seconds", type=float, default=0, help="Per-date work budget; exhausted dates remain resumable STAGING.")
    parser.add_argument("--detail-ttl-hours", type=float, default=36, help="Maximum age of reusable full stopping times.")
    parser.add_argument("--checkpoint-every-services", type=int, default=100)
    parser.add_argument("--checkpoint-interval-seconds", type=float, default=30)
    parser.add_argument("--storage-batch-size", type=int, default=50)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    if args.interval_seconds < 1:
        parser.error("--interval-seconds must be at least 1")
    if args.max_trains is not None and args.max_trains < 1:
        parser.error("--max-trains must be positive")
    if args.max_transient_resumes < 0:
        parser.error("--max-transient-resumes cannot be negative")
    if args.transient_resume_base_seconds < 1:
        parser.error("--transient-resume-base-seconds must be at least 1")
    if args.transient_resume_max_seconds < args.transient_resume_base_seconds:
        parser.error("--transient-resume-max-seconds must be at least the base delay")
    if not all(math.isfinite(value) for value in (args.max_run_seconds, args.max_date_seconds, args.detail_ttl_hours, args.checkpoint_interval_seconds)):
        parser.error("time budgets, detail TTL and checkpoint interval must be finite")
    if args.max_run_seconds < 0 or args.max_date_seconds < 0:
        parser.error("time budgets cannot be negative")
    if args.detail_ttl_hours <= 0:
        parser.error("--detail-ttl-hours must be positive")
    if args.checkpoint_every_services < 1 or args.checkpoint_interval_seconds <= 0 or args.storage_batch_size < 1:
        parser.error("checkpoint cadence and storage batch size must be positive")
    if args.scheduled and args.mode != "refresh":
        parser.error("--scheduled is only valid with --mode refresh")
    if args.scheduled and not settings.refresh_enabled:
        print(json.dumps({"status": "DISABLED", "reason": "rail timetable scheduled refresh is disabled"}))
        return 0
    if not args.dry_run and not settings.snapshot_enabled:
        parser.error("non-dry-run imports require TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED=true")
    limited_run = bool(args.train_number or args.prefix or args.max_discovery_queries or args.max_trains)
    if limited_run and not args.dry_run:
        parser.error("limited POC options require --dry-run so an incomplete batch cannot be activated")

    args._generation = datetime.now(SHANGHAI).date().isoformat()
    args._run_deadline = time.monotonic() + args.max_run_seconds if args.max_run_seconds else None
    try:
        with checkpoint_lock(args.checkpoint):
            return _run_with_transient_resume(
                lambda: _run_import_once(args, settings),
                enabled=args.auto_resume_transient,
                max_resumes=args.max_transient_resumes,
                base_delay_seconds=args.transient_resume_base_seconds,
                max_delay_seconds=args.transient_resume_max_seconds,
                deadline=args._run_deadline,
            )
    except RailCheckpointBusyError as exc:
        print(json.dumps({"status": "ALREADY_RUNNING", "message": str(exc)}))
        return EXIT_ALREADY_RUNNING
    except (OSError, RailCheckpointError, sqlite3.Error) as exc:
        print(json.dumps({"status": "SYSTEM_FAILED", "error_code": "RAIL_TIMETABLE_STORAGE_FAILURE", "message": str(exc)}))
        return EXIT_FAILED
    except KeyboardInterrupt:
        print(json.dumps({"status": "PAUSED", "error_code": "RAIL_TIMETABLE_INTERRUPTED"}))
        return 130


def _run_import_once(args: argparse.Namespace, settings: RailTimetableSettings) -> int:
    resume = args.resume or getattr(args, "_has_run", False)
    args._has_run = True
    checkpoint = CheckpointDocument(args.checkpoint, resume=resume)
    provider = Rail12306TimetableProvider(interval_seconds=args.interval_seconds)
    store = RailTimetableStore()
    dates = [args.date_from + timedelta(days=offset) for offset in range(args.days)]
    dates = _ordered_dates(dates, store, checkpoint, settings.freshness_hours)
    generation = getattr(args, "_generation", datetime.now(SHANGHAI).date().isoformat())
    run_deadline = getattr(args, "_run_deadline", None)
    started = time.monotonic()
    summaries: list[dict[str, Any]] = []
    attempted: set[str] = set()
    exit_code = 0
    try:
        for service_date in dates:
            if run_deadline is not None and time.monotonic() >= run_deadline:
                exit_code = EXIT_BUDGET_EXHAUSTED
                break
            key = service_date.isoformat()
            date_state = checkpoint.date_state(key)
            date_state["deferred_runs"] = 0
            date_state["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
            attempted.add(key)
            try:
                summary = _import_date(
                    service_date=service_date,
                    provider=provider,
                    store=store,
                    checkpoint=checkpoint,
                    checkpoint_path=args.checkpoint,
                    resume=resume,
                    dry_run=args.dry_run,
                    train_numbers=tuple(args.train_number),
                    prefixes=tuple(args.prefix) or ("G", "D", "C"),
                    max_discovery_queries=args.max_discovery_queries,
                    max_trains=args.max_trains,
                    refresh=args.mode == "refresh",
                    generation=generation,
                    detail_ttl_hours=getattr(args, "detail_ttl_hours", 36),
                    budget=ImportBudget(run_deadline=run_deadline, date_seconds=getattr(args, "max_date_seconds", 0)),
                    checkpoint_every=getattr(args, "checkpoint_every_services", 100),
                    checkpoint_interval=getattr(args, "checkpoint_interval_seconds", 30),
                    storage_batch_size=getattr(args, "storage_batch_size", 50),
                )
                summaries.append(summary)
                if summary.get("budget_exhausted"):
                    exit_code = max(exit_code, EXIT_BUDGET_EXHAUSTED)
            except RailTimetableAccessControlError as exc:
                summaries.append(_date_failure(key, date_state, "PAUSED", exc))
                exit_code = EXIT_ACCESS_CONTROL
                break
            except RailTimetableTemporaryError as exc:
                summaries.append(_date_failure(key, date_state, "RETRYABLE_FAILED", exc))
                if exit_code != EXIT_BUDGET_EXHAUSTED:
                    exit_code = EXIT_TRANSIENT_FAILURE
            except (RailTimetableProviderError, RailTimetableStoreError) as exc:
                summaries.append(_date_failure(key, date_state, "FAILED", exc))
                if exit_code == 0:
                    exit_code = EXIT_FAILED
        for service_date in dates:
            key = service_date.isoformat()
            if key not in attempted:
                state = checkpoint["dates"].setdefault(key, {"status": "PENDING"})
                state["deferred_runs"] = int(state.get("deferred_runs", 0)) + 1
        if not args.dry_run and exit_code != EXIT_ACCESS_CONTROL:
            store.cleanup(window_start=args.date_from, retention_days=settings.retention_days)
        checkpoint.save_manifest()
        status = {
            0: "DRY_RUN_COMPLETE" if args.dry_run else "COMPLETE",
            EXIT_FAILED: "PARTIAL_FAILED",
            EXIT_ACCESS_CONTROL: "PAUSED",
            EXIT_TRANSIENT_FAILURE: "RETRYABLE_FAILED",
            EXIT_BUDGET_EXHAUSTED: "BUDGET_EXHAUSTED",
        }[exit_code]
        print(json.dumps({
            "status": status, "generation": generation, "dates": summaries,
            "metrics": {
                "elapsed_seconds": round(time.monotonic() - started, 6),
                **_provider_metrics(provider),
                "checkpoint_seconds": round(checkpoint.write_seconds, 6),
                "checkpoint_writes": checkpoint.write_count,
                "checkpoint_bytes": checkpoint.bytes_written,
            },
        }, ensure_ascii=False))
        return exit_code
    finally:
        client = getattr(provider, "client", None)
        if client is not None:
            client.close()


def _date_failure(key: str, state: dict[str, Any], status: str, exc: Exception) -> dict[str, Any]:
    return {"service_date": key, "status": status, "message": str(exc), "metrics": state.get("metrics", {})}


def _ordered_dates(
    dates: list[date], store: RailTimetableStore, checkpoint: dict[str, Any], freshness_hours: int,
) -> list[date]:
    """Near-term gaps first; reserve tail work and age deferred dates fairly."""
    if not dates:
        return []
    urgent = [day for day in dates if store.active_batch(day, freshness_hours=freshness_hours) is None]
    remaining = [day for day in dates if day not in urgent]
    ordered = sorted(urgent) + sorted(remaining)
    tail = max(dates)
    if tail in ordered and len(ordered) > 1:
        ordered.remove(tail)
        ordered.insert(1, tail)
    deferred = checkpoint.get("dates", {})
    aged = [day for day in dates if int(deferred.get(day.isoformat(), {}).get("deferred_runs", 0)) >= 2]
    if aged:
        oldest = min(aged, key=lambda day: (-int(deferred[day.isoformat()]["deferred_runs"]), day))
        ordered.remove(oldest)
        ordered.insert(0, oldest)
    return ordered


def _provider_metrics(provider: Rail12306TimetableProvider) -> dict[str, int | float]:
    return dict(getattr(provider, "request_metrics", {}))


def _run_with_transient_resume(
    run_once: Callable[[], int],
    *,
    enabled: bool,
    max_resumes: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float | None = None,
) -> int:
    resume_count = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            print(json.dumps({"status": "BUDGET_EXHAUSTED", "error_code": "RAIL_TIMETABLE_TIME_BUDGET"}))
            return EXIT_BUDGET_EXHAUSTED
        exit_code = run_once()
        if exit_code != EXIT_TRANSIENT_FAILURE or not enabled:
            return exit_code
        if resume_count >= max_resumes:
            print(
                json.dumps(
                    {
                        "status": "RETRY_EXHAUSTED",
                        "error_code": "RAIL_TIMETABLE_TRANSIENT_RETRY_EXHAUSTED",
                        "resume_count": resume_count,
                    }
                )
            )
            return exit_code
        delay_seconds = min(max_delay_seconds, base_delay_seconds * (2**resume_count))
        if deadline is not None:
            delay_seconds = min(delay_seconds, max(0.0, deadline - time.monotonic()))
        resume_count += 1
        print(
            json.dumps(
                {
                    "status": "RETRY_WAIT",
                    "reason": "transient transport or server failure",
                    "resume_count": resume_count,
                    "delay_seconds": delay_seconds,
                }
            )
        )
        sleep(delay_seconds)


def _import_date(
    *,
    service_date: date,
    provider: Rail12306TimetableProvider,
    store: RailTimetableStore,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    resume: bool,
    dry_run: bool,
    train_numbers: tuple[str, ...],
    prefixes: tuple[str, ...],
    max_discovery_queries: int | None,
    max_trains: int | None,
    refresh: bool,
    generation: str | None = None,
    detail_ttl_hours: float = 36,
    budget: ImportBudget | None = None,
    checkpoint_every: int = 100,
    checkpoint_interval: float = 30,
    storage_batch_size: int = 50,
) -> dict[str, Any]:
    date_key = service_date.isoformat()
    date_state = checkpoint.date_state(date_key) if isinstance(checkpoint, CheckpointDocument) else checkpoint.setdefault("dates", {}).setdefault(
        date_key,
        {"batch_id": None, "completed_train_nos": [], "status": "PENDING"},
    )
    started = time.monotonic()
    metrics: dict[str, int | float] = {
        "discovery_seconds": 0.0, "detail_seconds": 0.0, "storage_seconds": 0.0,
        "checkpoint_seconds": 0.0, "checkpoint_writes": 0, "checkpoint_bytes": 0,
        "reused_count": 0, "resumed_count": 0, "fetched_count": 0,
    }
    network_before = _provider_metrics(provider)
    checkpoint_before = _checkpoint_metrics(checkpoint)
    budget = budget or ImportBudget()
    provider.remaining_budget = budget.remaining
    generation = generation or datetime.now(SHANGHAI).date().isoformat()
    if refresh and date_state.get("generation") != generation:
        # A new daily run must see additions/cancellations. Old committed rows
        # remain a reusable source, but their discovery list is never current.
        date_state["reuse_batch_id"] = date_state.get("batch_id")
        date_state.update({"generation": generation, "batch_id": None, "status": "PENDING", "completed_train_nos": []})
        date_state.pop("discovery", None)
    else:
        date_state.setdefault("generation", generation)
    completed: set[str] = set()
    pending_services: list[RailServiceInput] = []
    batch_id: str | None = None

    def persist() -> None:
        date_state["completed_train_nos"] = sorted(completed)
        _finish_metrics(metrics, started, network_before, provider, checkpoint_before, checkpoint)
        date_state["metrics"] = dict(metrics)
        _persist_date(checkpoint_path, checkpoint, date_key)

    cadence = CheckpointCadence(persist, every=checkpoint_every, interval=checkpoint_interval)

    def storage_call(operation: Callable[[], Any]) -> Any:
        operation_started = time.monotonic()
        try:
            return operation()
        finally:
            metrics["storage_seconds"] += time.monotonic() - operation_started

    def flush_services() -> None:
        if not pending_services:
            return
        if batch_id is None:
            raise RailTimetableStoreError("a STAGING batch is required before committing service details")
        storage_call(lambda: store.upsert_services(batch_id, pending_services))
        completed.update(service.train_no_internal for service in pending_services)
        pending_services.clear()

    def summarize(**values: Any) -> dict[str, Any]:
        _finish_metrics(metrics, started, network_before, provider, checkpoint_before, checkpoint)
        date_state["metrics"] = dict(metrics)
        return {"service_date": date_key, **values, "metrics": dict(metrics)}

    if resume and not dry_run and not refresh:
        active = store.active_batch(service_date, freshness_hours=None)
        if active is not None:
            completed = set(store.batch_service_progress(active.batch_id))
            date_state.update(
                {
                    "batch_id": active.batch_id,
                    "status": "ACTIVE",
                    "service_count": active.service_count,
                    "stop_count": active.stop_count,
                }
            )
            metrics["resumed_count"] = len(completed)
            cadence.tick(force=True)
            return summarize(discovered_count=active.service_count, service_count=active.service_count,
                             stop_count=active.stop_count, query_count=0, activated=False, already_active=True)
    if resume and refresh and not dry_run and date_state.get("batch_id"):
        active = store.get_batch(str(date_state["batch_id"]))
        if active is not None and active.status == "ACTIVE" and active.service_date == service_date:
            completed = set(store.batch_service_progress(active.batch_id))
            date_state.update({"status": "ACTIVE", "service_count": active.service_count, "stop_count": active.stop_count})
            metrics["resumed_count"] = len(completed)
            cadence.tick(force=True)
            return summarize(discovered_count=active.service_count, service_count=active.service_count,
                             stop_count=active.stop_count, query_count=0, activated=False, already_active=True)
    try:
        cadence.tick(force=True)
        budget.check()
        discovery_started = time.monotonic()
        checkpoint_discovery_before = _checkpoint_metrics(checkpoint)[0]
        try:
            if train_numbers:
                discovered, diagnostics = provider.discover_exact_services(service_date, train_numbers)
            else:
                discovery_state = date_state.setdefault("discovery", {})

                def discovery_checkpoint() -> None:
                    cadence.tick()
                    budget.check()

                discovered, diagnostics = provider.discover_services(
                    service_date, prefixes=prefixes, max_queries=max_discovery_queries,
                    resume_state=discovery_state, checkpoint_callback=discovery_checkpoint,
                )
        finally:
            metrics["discovery_seconds"] += max(0.0, time.monotonic() - discovery_started -
                (_checkpoint_metrics(checkpoint)[0] - checkpoint_discovery_before))
        cadence.tick(force=True)
        if not dry_run and date_state.get("discovery", {}).get("pending_prefixes"):
            raise RailTimetableProviderError("discovery is incomplete; refusing batch activation")
        if max_trains is not None:
            discovered = discovered[:max_trains]
        if not discovered:
            raise RailTimetableProviderError(f"no G/D/C services discovered for {date_key}")
        if dry_run:
            for item in discovered:
                budget.check()
                detail_started = time.monotonic()
                try:
                    provider.fetch_complete_service(item)
                finally:
                    metrics["detail_seconds"] += time.monotonic() - detail_started
                metrics["fetched_count"] += 1
            date_state.update({"status": "DRY_RUN_COMPLETE", "discovered_count": diagnostics.service_count,
                               "fetched_count": metrics["fetched_count"]})
            cadence.tick(force=True)
            return summarize(discovered_count=diagnostics.service_count, fetched_count=metrics["fetched_count"],
                             query_count=diagnostics.query_count, activated=False)

        batch_id = storage_call(lambda: _resume_or_begin_batch(store, service_date, date_state, resume))
        committed = storage_call(lambda: store.batch_service_progress(batch_id))
        discovered_nos = {item.train_no_internal for item in discovered}
        obsolete = set(committed) - discovered_nos
        if obsolete:
            storage_call(lambda: store.delete_services(batch_id, obsolete))
            committed = {train_no: value for train_no, value in committed.items() if train_no in discovered_nos}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=detail_ttl_hours)
        completed = {
            item.train_no_internal for item in discovered
            if item.train_no_internal in committed
            and committed[item.train_no_internal].summary_fingerprint == item.summary_fingerprint
            and committed[item.train_no_internal].fetched_at >= cutoff
        }
        metrics["resumed_count"] = len(completed)
        cadence.tick(force=True)
        if refresh:
            active_batch_id, _ = storage_call(lambda: store.active_service_fingerprints(service_date))
            sources = list(dict.fromkeys(value for value in (date_state.get("reuse_batch_id"), active_batch_id) if value and value != batch_id))
            reusable: dict[str, list[str]] = {}
            best_source: dict[str, tuple[str, datetime]] = {}
            discovered_by_no = {item.train_no_internal: item for item in discovered}
            for source_id in sources:
                progress = storage_call(lambda: store.batch_service_progress(source_id))
                for train_no, value in progress.items():
                    item = discovered_by_no.get(train_no)
                    if (item is not None and train_no not in completed and value.summary_fingerprint == item.summary_fingerprint
                            and value.fetched_at >= cutoff and (train_no not in best_source or value.fetched_at > best_source[train_no][1])):
                        best_source[train_no] = (source_id, value.fetched_at)
            for train_no, (source_id, _) in best_source.items():
                reusable.setdefault(source_id, []).append(train_no)
            for source_id, train_nos in reusable.items():
                for offset in range(0, len(train_nos), storage_batch_size):
                    budget.check()
                    chunk = train_nos[offset:offset + storage_batch_size]
                    copied = storage_call(lambda: store.copy_services(source_id, batch_id, chunk))
                    completed.update(copied)
                    metrics["reused_count"] += len(copied)
                    cadence.tick()
        expected_service_count = len(discovered)
        for item in discovered:
            if item.train_no_internal in completed:
                continue
            budget.check()
            detail_started = time.monotonic()
            unusable_error: Exception | None = None
            try:
                service = provider.fetch_complete_service(item)
            except (RailTimetableServiceWithdrawnError, RailTimetableAmbiguousStopsError, RailTimetableUnsupportedStationError) as exc:
                unusable_error = exc
            finally:
                metrics["detail_seconds"] += time.monotonic() - detail_started
            if unusable_error is not None:
                _reconcile_unusable_service(date_state, item, unusable_error)
                storage_call(lambda: store.delete_services(batch_id, (item.train_no_internal,)))
                expected_service_count -= 1
                cadence.tick(force=True)
                continue
            pending_services.append(service)
            metrics["fetched_count"] += 1
            if len(pending_services) >= storage_batch_size:
                flush_services()
            cadence.tick()
        flush_services()
        budget.check()
        staged = storage_call(lambda: store.get_batch(batch_id))
        if staged is None or staged.service_count != expected_service_count:
            raise RailTimetableStoreError(
                "discovery completeness gate failed: "
                f"discovered={expected_service_count}, staged={staged.service_count if staged else 0}"
            )
        activated = storage_call(lambda: store.activate_batch(batch_id))
    except RailTimetableBudgetExceeded:
        flush_services()
        date_state["status"] = "STAGING" if date_state.get("batch_id") else "PENDING"
        date_state["error_code"] = "RAIL_TIMETABLE_TIME_BUDGET"
        cadence.tick(force=True)
        return summarize(status="BUDGET_EXHAUSTED", budget_exhausted=True, activated=False,
                         service_count=len(completed))
    except (RailTimetableProviderError, RailTimetableStoreError, KeyboardInterrupt) as exc:
        if not isinstance(exc, RailTimetableStoreError):
            flush_services()
        recoverable = isinstance(exc, (RailTimetableAccessControlError, RailTimetableTemporaryError, KeyboardInterrupt))
        date_state["status"] = "PAUSED" if isinstance(exc, (RailTimetableAccessControlError, KeyboardInterrupt)) else "STAGING" if recoverable and batch_id else "FAILED"
        date_state["error_code"] = (
            "RAIL_TIMETABLE_ACCESS_CONTROL" if isinstance(exc, RailTimetableAccessControlError)
            else "RAIL_TIMETABLE_TRANSIENT_FAILURE" if isinstance(exc, RailTimetableTemporaryError)
            else "RAIL_TIMETABLE_INTERRUPTED" if isinstance(exc, KeyboardInterrupt)
            else "RAIL_TIMETABLE_IMPORT_FAILED"
        )
        if batch_id:
            if recoverable:
                storage_call(lambda: store.record_error(batch_id, str(exc)))
            else:
                storage_call(lambda: store.fail_batch(batch_id, str(exc)))
        cadence.tick(force=True)
        raise
    date_state.update(
        {
            "status": "ACTIVE",
            "service_count": activated.service_count,
            "stop_count": activated.stop_count,
        }
    )
    date_state.pop("error_code", None)
    cadence.tick(force=True)
    return summarize(discovered_count=expected_service_count, service_count=activated.service_count,
                     stop_count=activated.stop_count, query_count=diagnostics.query_count, activated=True)


def _reconcile_unusable_service(date_state: dict[str, Any], item: DiscoveredRailService, exc: Exception) -> None:
    discovery = date_state.get("discovery")
    services = discovery.get("services") if isinstance(discovery, dict) else None
    if not isinstance(services, dict) or services.pop(item.train_no_internal, None) is None:
        raise RailTimetableProviderError("unusable timetable service cannot be reconciled with discovery checkpoint")
    if isinstance(exc, RailTimetableServiceWithdrawnError):
        logger.warning("rail_timetable_service_withdrawn service_date=%s train_number=%s", item.service_date, item.train_number)
        return
    quarantined = discovery.setdefault("quarantined_services", {})
    if not isinstance(quarantined, dict):
        raise RailTimetableProviderError("timetable discovery quarantine checkpoint is malformed")
    if isinstance(exc, RailTimetableUnsupportedStationError):
        quarantined[item.train_no_internal] = {
            "train_number": item.train_number, "reason": "UNSUPPORTED_STATION", "station_name": exc.station_name,
        }
    elif isinstance(exc, RailTimetableAmbiguousStopsError):
        quarantined[item.train_no_internal] = {
            "train_number": item.train_number, "service_date": item.service_date.isoformat(),
            "origin_station_name": item.origin_station_name, "destination_station_name": item.destination_station_name,
            "origin_departure_time": exc.origin_departure_time, "destination_arrival_time": exc.destination_arrival_time,
            "destination_arrival_day_offset": exc.destination_arrival_day_offset,
            "expected_stop_count": exc.expected_stop_count, "returned_stop_count": exc.returned_stop_count,
            "reason": "AMBIGUOUS_EXTRA_STOPS", "quarantined_at": datetime.now(timezone.utc).isoformat(),
        }
    logger.warning("rail_timetable_service_quarantined service_date=%s train_number=%s reason=%s",
                   item.service_date, item.train_number, quarantined[item.train_no_internal]["reason"])


def _checkpoint_metrics(checkpoint: dict[str, Any]) -> tuple[float, int, int]:
    if isinstance(checkpoint, CheckpointDocument):
        return checkpoint.write_seconds, checkpoint.write_count, checkpoint.bytes_written
    return 0.0, 0, 0


def _finish_metrics(
    metrics: dict[str, int | float], started: float, network_before: dict[str, int | float],
    provider: Rail12306TimetableProvider, checkpoint_before: tuple[float, int, int], checkpoint: dict[str, Any],
) -> None:
    for key, value in _provider_metrics(provider).items():
        metrics[key] = value - network_before.get(key, 0)
    current = _checkpoint_metrics(checkpoint)
    metrics.update({
        "checkpoint_seconds": current[0] - checkpoint_before[0],
        "checkpoint_writes": current[1] - checkpoint_before[1],
        "checkpoint_bytes": current[2] - checkpoint_before[2],
        "elapsed_seconds": time.monotonic() - started,
    })


def _persist_date(path: Path, checkpoint: dict[str, Any], key: str) -> None:
    if isinstance(checkpoint, CheckpointDocument):
        checkpoint.save_date(key)
    else:
        _save_checkpoint(path, checkpoint)


def _resume_or_begin_batch(
    store: RailTimetableStore,
    service_date: date,
    date_state: dict[str, Any],
    resume: bool,
) -> str:
    existing_id = str(date_state.get("batch_id") or "")
    failed_source_id: str | None = None
    previously_completed: tuple[str, ...] = ()
    if resume and existing_id:
        existing = store.get_batch(existing_id)
        if existing and existing.status == "STAGING" and existing.service_date == service_date:
            date_state["completed_train_nos"] = sorted(store.batch_service_progress(existing.batch_id))
            return existing.batch_id
        if existing and existing.status == "FAILED" and existing.service_date == service_date:
            failed_source_id = existing.batch_id
            previously_completed = tuple(store.batch_service_progress(existing.batch_id))
    batch_id = store.begin_batch(service_date, SOURCE_VERSION)
    date_state["batch_id"] = batch_id
    copied = (
        store.copy_services(failed_source_id, batch_id, previously_completed)
        if failed_source_id and previously_completed
        else set()
    )
    date_state["completed_train_nos"] = sorted(copied)
    date_state["status"] = "STAGING"
    return batch_id


def _load_checkpoint(path: Path) -> dict[str, Any]:
    return CheckpointDocument(path, resume=True)


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    if isinstance(payload, CheckpointDocument):
        payload.save_manifest()
    else:
        # Compatibility for old callers constructing a fresh in-memory fixture.
        # Production imports always use CheckpointDocument, which reads v1 only.
        atomic_write_json(path, payload)


def _mark_checkpoint_paused(checkpoint: dict[str, Any]) -> None:
    date_states = checkpoint.get("dates")
    if not isinstance(date_states, dict):
        return
    for date_state in reversed(list(date_states.values())):
        if not isinstance(date_state, dict) or date_state.get("status") not in {"PENDING", "STAGING", "PAUSED"}:
            continue
        date_state["status"] = "PAUSED"
        discovery = date_state.get("discovery")
        if isinstance(discovery, dict) and discovery.get("status") in {"RUNNING", "PAUSED"}:
            discovery["status"] = "PAUSED"
        return


if __name__ == "__main__":
    raise SystemExit(main())
