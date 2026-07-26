from __future__ import annotations

from datetime import date

from app.core.context import RequestContext
from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import plan_trip
from app.services.planning_progress import PlanningProgressUpdate
from app.services.task_queue import PlanningDeadline


class _ControllableClock:
    def __init__(self) -> None:
        self.expired = False

    def __call__(self) -> float:
        return 2.0 if self.expired else 0.0


class _ExpireAfterFirstPlanSink:
    def __init__(self, clock: _ControllableClock) -> None:
        self.clock = clock
        self.updates: list[PlanningProgressUpdate] = []

    def publish(self, update: PlanningProgressUpdate) -> None:
        self.updates.append(update)
        self.clock.expired = True


def _request(request_id: str) -> TravelRequest:
    return TravelRequest(
        request_id=request_id,
        raw_user_input="2026年8月20日从上海到武汉，铁路或航班都可以",
        origin_text="上海",
        destination_text="武汉",
        travel_date=date(2026, 8, 20),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )


def _context(request_id: str) -> RequestContext:
    return RequestContext(
        request_id=request_id,
        trace_id=f"trace_{request_id}",
        correlation_id=f"corr_{request_id}",
        idempotency_key=f"idem_{request_id}",
    )


def test_observation_deadline_records_would_timeout_without_stopping_work():
    clock = _ControllableClock()
    deadline = PlanningDeadline(timeout_seconds=1, mode="observe", clock=clock)
    clock.expired = True

    assert deadline.allow_new_branch("FLIGHT")
    assert deadline.would_timeout
    assert not deadline.enforced
    assert deadline.outcome(has_plans=True) == "WOULD_TIMEOUT"


def test_enforced_deadline_keeps_first_complete_plan_as_partial(monkeypatch):
    monkeypatch.setenv("TRAVEL_PROVIDER_FAMILY_PARALLEL_ENABLED", "false")
    request_id = "req_deadline_partial"
    clock = _ControllableClock()
    deadline = PlanningDeadline(timeout_seconds=1, mode="enforce", clock=clock)
    sink = _ExpireAfterFirstPlanSink(clock)

    response = plan_trip(
        _request(request_id),
        _context(request_id),
        progress_sink=sink,
        deadline=deadline,
    )

    assert sink.updates
    assert deadline.enforced
    assert response.planning_status == "PARTIAL"
    assert response.plans
    assert any("服务端规划期限已到" in warning for warning in response.user_visible_warnings)
    assert deadline.outcome(has_plans=True) == "ENFORCED_PARTIAL"


def test_enforced_deadline_without_a_complete_plan_returns_explainable_failed(monkeypatch):
    monkeypatch.setenv("TRAVEL_PROVIDER_FAMILY_PARALLEL_ENABLED", "false")
    request_id = "req_deadline_failed"
    clock = _ControllableClock()
    deadline = PlanningDeadline(timeout_seconds=1, mode="enforce", clock=clock)
    clock.expired = True

    response = plan_trip(
        _request(request_id),
        _context(request_id),
        deadline=deadline,
    )

    assert deadline.enforced
    assert response.planning_status == "FAILED"
    assert response.plans == []
    assert "travel_plan" in response.missing_components
    assert any("服务端规划期限已到" in warning for warning in response.user_visible_warnings)
    assert deadline.outcome(has_plans=False) == "ENFORCED_FAILED"
