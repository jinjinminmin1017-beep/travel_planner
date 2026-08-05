from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.data_sources.config_loader import load_project_env, load_rail_timetable_settings  # noqa: E402
from app.data_sources.rail_12306_timetable_provider import (  # noqa: E402
    Rail12306TimetableProvider,
    RailTimetableAccessControlError,
    RailTimetableProviderError,
    SOURCE_VERSION,
)
from app.services.rail_timetable_store import RailTimetableStore, RailTimetableStoreError  # noqa: E402


DEFAULT_CHECKPOINT = ROOT / "logs" / "rail_timetable_import_checkpoint.json"


def main() -> int:
    load_project_env(ROOT / ".env")
    settings = load_rail_timetable_settings()
    parser = argparse.ArgumentParser(
        description="Import current G/D/C timetable snapshots with low-frequency, resumable 12306 requests."
    )
    parser.add_argument("--mode", choices=("bootstrap", "refresh"), default="bootstrap")
    parser.add_argument("--date-from", type=date.fromisoformat, default=date.today())
    parser.add_argument("--days", type=int, default=settings.horizon_days)
    parser.add_argument("--interval-seconds", type=float, default=settings.import_interval_seconds)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--train-number", action="append", default=[])
    parser.add_argument("--prefix", action="append", default=[])
    parser.add_argument("--max-discovery-queries", type=int)
    parser.add_argument("--max-trains", type=int)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    if args.interval_seconds < 1:
        parser.error("--interval-seconds must be at least 1")
    if args.max_trains is not None and args.max_trains < 1:
        parser.error("--max-trains must be positive")
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

    checkpoint = _load_checkpoint(args.checkpoint) if args.resume else {"version": 1, "dates": {}}
    provider = Rail12306TimetableProvider(interval_seconds=args.interval_seconds)
    store = RailTimetableStore()
    dates = [args.date_from + timedelta(days=offset) for offset in range(args.days)]
    if args.mode == "refresh":
        dates = sorted(dates, key=lambda item: (item != dates[-1], item))

    summaries: list[dict[str, Any]] = []
    try:
        for service_date in dates:
            summaries.append(
                _import_date(
                    service_date=service_date,
                    provider=provider,
                    store=store,
                    checkpoint=checkpoint,
                    checkpoint_path=args.checkpoint,
                    resume=args.resume,
                    dry_run=args.dry_run,
                    train_numbers=tuple(args.train_number),
                    prefixes=tuple(args.prefix) or ("G", "D", "C"),
                    max_discovery_queries=args.max_discovery_queries,
                    max_trains=args.max_trains,
                    refresh=args.mode == "refresh",
                )
            )
    except RailTimetableAccessControlError as exc:
        _mark_checkpoint_paused(checkpoint)
        _save_checkpoint(args.checkpoint, checkpoint)
        print(json.dumps({"status": "PAUSED", "error_code": "RAIL_TIMETABLE_ACCESS_CONTROL", "message": str(exc)}, ensure_ascii=False))
        return 2
    except (RailTimetableProviderError, RailTimetableStoreError) as exc:
        _save_checkpoint(args.checkpoint, checkpoint)
        print(json.dumps({"status": "FAILED", "error_code": "RAIL_TIMETABLE_IMPORT_FAILED", "message": str(exc)}, ensure_ascii=False))
        return 1

    if not args.dry_run:
        store.cleanup(window_start=args.date_from, retention_days=settings.retention_days)
    _save_checkpoint(args.checkpoint, checkpoint)
    print(json.dumps({"status": "DRY_RUN_COMPLETE" if args.dry_run else "COMPLETE", "dates": summaries}, ensure_ascii=False))
    return 0


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
) -> dict[str, Any]:
    date_key = service_date.isoformat()
    date_state = checkpoint.setdefault("dates", {}).setdefault(
        date_key,
        {"batch_id": None, "completed_train_nos": [], "status": "PENDING"},
    )
    if resume and not dry_run and not refresh:
        active = store.active_batch(service_date, freshness_hours=None)
        if active is not None:
            discovery_state = date_state.get("discovery")
            discovery_services = discovery_state.get("services") if isinstance(discovery_state, dict) else None
            if isinstance(discovery_services, dict) and len(discovery_services) == active.service_count:
                date_state["completed_train_nos"] = sorted(str(value) for value in discovery_services)
            date_state.update(
                {
                    "batch_id": active.batch_id,
                    "status": "ACTIVE",
                    "service_count": active.service_count,
                    "stop_count": active.stop_count,
                }
            )
            _save_checkpoint(checkpoint_path, checkpoint)
            return {
                "service_date": date_key,
                "discovered_count": active.service_count,
                "service_count": active.service_count,
                "stop_count": active.stop_count,
                "query_count": 0,
                "activated": False,
                "already_active": True,
            }
    if train_numbers:
        discovered, diagnostics = provider.discover_exact_services(service_date, train_numbers)
    else:
        discovery_state = date_state.setdefault("discovery", {})
        discovered, diagnostics = provider.discover_services(
            service_date,
            prefixes=prefixes,
            max_queries=max_discovery_queries,
            resume_state=discovery_state,
            checkpoint_callback=lambda: _save_checkpoint(checkpoint_path, checkpoint),
        )
    if max_trains is not None:
        discovered = discovered[:max_trains]
    if not discovered:
        raise RailTimetableProviderError(f"no G/D/C services discovered for {date_key}")

    if dry_run:
        fetched = [provider.fetch_complete_service(item) for item in discovered]
        date_state.update(
            {
                "status": "DRY_RUN_COMPLETE",
                "discovered_count": diagnostics.service_count,
                "fetched_count": len(fetched),
                "response_hashes": list(diagnostics.response_hashes),
            }
        )
        _save_checkpoint(checkpoint_path, checkpoint)
        return {
            "service_date": date_key,
            "discovered_count": diagnostics.service_count,
            "fetched_count": len(fetched),
            "query_count": diagnostics.query_count,
            "activated": False,
        }

    batch_id = _resume_or_begin_batch(store, service_date, date_state, resume)
    _save_checkpoint(checkpoint_path, checkpoint)
    completed = set(str(value) for value in date_state.get("completed_train_nos", []))
    active_batch_id, active_fingerprints = store.active_service_fingerprints(service_date)
    try:
        for item in discovered:
            if item.train_no_internal in completed:
                continue
            if (
                refresh
                and active_batch_id
                and active_fingerprints.get(item.train_no_internal) == item.summary_fingerprint
                and store.copy_service(active_batch_id, batch_id, item.train_no_internal)
            ):
                pass
            else:
                store.upsert_service(batch_id, provider.fetch_complete_service(item))
            completed.add(item.train_no_internal)
            date_state["completed_train_nos"] = sorted(completed)
            date_state["status"] = "STAGING"
            _save_checkpoint(checkpoint_path, checkpoint)
        staged = store.get_batch(batch_id)
        if staged is None or staged.service_count != len(discovered):
            raise RailTimetableStoreError(
                f"discovery completeness gate failed: discovered={len(discovered)}, staged={staged.service_count if staged else 0}"
            )
        activated = store.activate_batch(batch_id)
    except Exception as exc:
        if isinstance(exc, RailTimetableAccessControlError):
            store.record_error(batch_id, str(exc))
            date_state["status"] = "PAUSED"
        else:
            store.fail_batch(batch_id, str(exc))
            date_state["status"] = "FAILED"
        _save_checkpoint(checkpoint_path, checkpoint)
        raise
    date_state.update(
        {
            "status": "ACTIVE",
            "service_count": activated.service_count,
            "stop_count": activated.stop_count,
            "response_hashes": list(diagnostics.response_hashes),
        }
    )
    _save_checkpoint(checkpoint_path, checkpoint)
    return {
        "service_date": date_key,
        "discovered_count": diagnostics.service_count,
        "service_count": activated.service_count,
        "stop_count": activated.stop_count,
        "query_count": diagnostics.query_count,
        "activated": True,
    }


def _resume_or_begin_batch(
    store: RailTimetableStore,
    service_date: date,
    date_state: dict[str, Any],
    resume: bool,
) -> str:
    existing_id = str(date_state.get("batch_id") or "")
    failed_source_id: str | None = None
    previously_completed = tuple(str(value) for value in date_state.get("completed_train_nos", []))
    if resume and existing_id:
        existing = store.get_batch(existing_id)
        if existing and existing.status == "STAGING" and existing.service_date == service_date:
            return existing.batch_id
        if existing and existing.status == "FAILED" and existing.service_date == service_date:
            failed_source_id = existing.batch_id
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
    if not path.exists():
        return {"version": 1, "dates": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("dates"), dict):
        raise RailTimetableProviderError("rail timetable checkpoint has an unsupported shape")
    return payload


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


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
