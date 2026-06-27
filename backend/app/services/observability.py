from __future__ import annotations

from collections import Counter
from typing import Any

from app.models.schemas import TravelPlanResponse, now_timepoint

_COUNTERS: Counter[str] = Counter()
_PROVIDER_FAILURES: Counter[str] = Counter()
_APP_EVENTS: Counter[str] = Counter()
_APP_EVENT_LINKS: list[dict[str, Any]] = []


def record_travel_response(response: TravelPlanResponse) -> None:
    _COUNTERS["travel_requests"] += 1
    _COUNTERS[f"planning_status.{response.planning_status}"] += 1
    if response.planning_status == "COMPLETE":
        _COUNTERS["planning_success"] += 1
    if response.planning_status == "PARTIAL":
        _COUNTERS["planning_partial"] += 1
    for failure in response.source_failures:
        _COUNTERS["provider_failures"] += 1
        _PROVIDER_FAILURES[failure.source_id] += 1
    validation = response.recommendation_result.llm_validation_result if response.recommendation_result else None
    if validation and validation.repair_attempted:
        _COUNTERS["llm_repair_attempts"] += 1
    if validation and validation.repair_success:
        _COUNTERS["llm_repair_success"] += 1


def metrics_snapshot() -> dict[str, Any]:
    return {
        "generated_at": now_timepoint().model_dump(mode="json"),
        "counters": dict(_COUNTERS),
        "provider_failures": dict(_PROVIDER_FAILURES),
        "app_events": dict(_APP_EVENTS),
        "app_event_links": list(_APP_EVENT_LINKS[-50:]),
    }


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
