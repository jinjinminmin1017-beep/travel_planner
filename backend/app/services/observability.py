from __future__ import annotations

import sqlite3
from collections import Counter
from threading import RLock
from typing import Any

from app.models.schemas import TravelPlanResponse, now_timepoint

_COUNTERS: Counter[str] = Counter()
_PROVIDER_FAILURES: Counter[str] = Counter()
_APP_EVENTS: Counter[str] = Counter()
_APP_EVENT_LINKS: list[dict[str, Any]] = []
_PLANNING_LATENCY_SAMPLES: dict[str, list[float]] = {
    "first_usable_plan_latency_ms": [],
    "final_result_latency_ms": [],
}
_PLANNING_DEADLINE_OUTCOMES: Counter[str] = Counter()
_RAIL_RUNTIME_SAMPLES: dict[str, list[float]] = {
    "local_search_latency_ms": [],
    "inventory_verification_latency_ms": [],
}
_RAIL_RUNTIME_COUNTERS: Counter[str] = Counter()
_METRICS_LOCK = RLock()


def record_travel_response(response: TravelPlanResponse) -> None:
    _COUNTERS["travel_requests"] += 1
    _COUNTERS[f"planning_status.{response.planning_status}"] += 1
    if response.planning_status == "COMPLETE":
        _COUNTERS["planning_success"] += 1
    if response.planning_status == "PARTIAL":
        _COUNTERS["planning_partial"] += 1
    if response.planning_status == "NO_MATCH":
        _COUNTERS["planning_no_match"] += 1
        analysis = response.constraint_analysis
        _COUNTERS["constraint_alternatives"] += len(analysis.alternatives) if analysis else 0
        for alternative in analysis.alternatives if analysis else []:
            for violation in alternative.violations:
                _COUNTERS[f"constraint_violation.{violation.constraint_type}"] += 1
        for coverage in analysis.coverage if analysis else []:
            _COUNTERS[f"constraint_coverage.{coverage.transport_mode}.{coverage.status}"] += 1
    for failure in response.source_failures:
        _COUNTERS["provider_failures"] += 1
        _PROVIDER_FAILURES[failure.source_id] += 1
    validation = response.recommendation_result.llm_validation_result if response.recommendation_result else None
    if validation and validation.repair_attempted:
        _COUNTERS["llm_repair_attempts"] += 1
    if validation and validation.repair_success:
        _COUNTERS["llm_repair_success"] += 1


def metrics_snapshot() -> dict[str, Any]:
    with _METRICS_LOCK:
        planning_latency = {
            name: _summarize_samples(samples)
            for name, samples in _PLANNING_LATENCY_SAMPLES.items()
        }
        deadline_outcomes = dict(_PLANNING_DEADLINE_OUTCOMES)
        rail_runtime = {
            name: _summarize_samples(samples)
            for name, samples in _RAIL_RUNTIME_SAMPLES.items()
        }
        rail_counters = dict(_RAIL_RUNTIME_COUNTERS)
    rail_coverage: list[dict[str, Any]] = []
    try:
        from app.data_sources.config_loader import load_rail_timetable_settings
        from app.services.rail_timetable_store import RailTimetableStore

        settings = load_rail_timetable_settings()
        if settings.snapshot_enabled:
            rail_coverage = [
                {
                    "service_date": item.service_date.isoformat(),
                    "status": item.status,
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                    "service_count": item.service_count,
                    "stop_count": item.stop_count,
                    "fresh": item.fresh,
                }
                for item in RailTimetableStore().coverage(freshness_hours=settings.freshness_hours)
            ]
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        rail_coverage = []
    return {
        "generated_at": now_timepoint().model_dump(mode="json"),
        "counters": dict(_COUNTERS),
        "provider_failures": dict(_PROVIDER_FAILURES),
        "app_events": dict(_APP_EVENTS),
        "app_event_links": list(_APP_EVENT_LINKS[-50:]),
        "planning_latency_ms": planning_latency,
        "planning_deadline_outcomes": deadline_outcomes,
        "rail_timetable_coverage": rail_coverage,
        "rail_runtime": rail_runtime,
        "rail_runtime_counters": rail_counters,
    }


def _summarize_samples(samples: list[float]) -> dict[str, float | int | None]:
    if not samples:
        return {"count": 0, "p50": None, "p95": None, "p99": None}
    ordered = sorted(samples)

    def percentile(ratio: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
        return round(ordered[index], 1)

    return {
        "count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def record_async_planning_metrics(
    *,
    first_usable_plan_latency_ms: float | None,
    final_result_latency_ms: float,
    progressive_snapshot_count: int,
    deadline_outcome: str,
    route_cache_hits: int,
    route_cache_misses: int,
    location_cache_hits: int,
    location_cache_misses: int,
) -> None:
    with _METRICS_LOCK:
        if first_usable_plan_latency_ms is not None:
            _PLANNING_LATENCY_SAMPLES["first_usable_plan_latency_ms"].append(first_usable_plan_latency_ms)
        _PLANNING_LATENCY_SAMPLES["final_result_latency_ms"].append(final_result_latency_ms)
        for samples in _PLANNING_LATENCY_SAMPLES.values():
            del samples[:-200]
        _COUNTERS["planning_progress_snapshots"] += progressive_snapshot_count
        _COUNTERS["planning_route_cache_hits"] += route_cache_hits
        _COUNTERS["planning_route_cache_misses"] += route_cache_misses
        _COUNTERS["planning_location_cache_hits"] += location_cache_hits
        _COUNTERS["planning_location_cache_misses"] += location_cache_misses
        _PLANNING_DEADLINE_OUTCOMES[deadline_outcome] += 1


def record_rail_local_search_metrics(
    *,
    elapsed_ms: float,
    candidate_count: int,
    scanned_leg_count: int,
) -> None:
    with _METRICS_LOCK:
        _RAIL_RUNTIME_SAMPLES["local_search_latency_ms"].append(elapsed_ms)
        del _RAIL_RUNTIME_SAMPLES["local_search_latency_ms"][:-200]
        _RAIL_RUNTIME_COUNTERS["local_searches"] += 1
        _RAIL_RUNTIME_COUNTERS["local_candidates"] += candidate_count
        _RAIL_RUNTIME_COUNTERS["local_scanned_legs"] += scanned_leg_count


def record_rail_inventory_metrics(
    *,
    elapsed_ms: float,
    queried_group_count: int,
    external_call_count: int,
    budget_exhausted: bool,
) -> None:
    with _METRICS_LOCK:
        _RAIL_RUNTIME_SAMPLES["inventory_verification_latency_ms"].append(elapsed_ms)
        del _RAIL_RUNTIME_SAMPLES["inventory_verification_latency_ms"][:-200]
        _RAIL_RUNTIME_COUNTERS["inventory_verifications"] += 1
        _RAIL_RUNTIME_COUNTERS["inventory_queried_groups"] += queried_group_count
        _RAIL_RUNTIME_COUNTERS["inventory_external_calls"] += external_call_count
        if budget_exhausted:
            _RAIL_RUNTIME_COUNTERS["inventory_budget_exhausted"] += 1


def record_app_event(
    event_type: str,
    request_id: str | None = None,
    trace_id: str | None = None,
    plan_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _APP_EVENTS[event_type] += 1
    _APP_EVENT_LINKS.append(
        {
            "event_type": event_type,
            "request_id": request_id,
            "trace_id": trace_id,
            "plan_id": plan_id,
            "metadata_keys": sorted((metadata or {}).keys()),
            "received_at": now_timepoint().model_dump(mode="json"),
        }
    )
    del _APP_EVENT_LINKS[:-100]
