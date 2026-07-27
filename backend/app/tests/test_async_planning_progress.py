from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.core.context import RequestContext
from app.models.schemas import (
    AsyncJob,
    AsyncJobStatus,
    PlanningStatus,
    RecommendationEligibility,
    RecommendationType,
    TravelHardConstraints,
    TravelPlanResponse,
    TravelRequest,
    TravelSoftPreferences,
    now_timepoint,
)
from app.services.planner import plan_trip
from app.services.planning_progress import PlanningExecutionMetrics, PlanningProgressUpdate
from app.services.store import (
    begin_async_job,
    get_async_job_response,
    invalidate_async_job_generation,
    save_async_job_response,
    save_async_job_response_if_current,
)


class _CollectingProgressSink:
    def __init__(self) -> None:
        self.updates: list[PlanningProgressUpdate] = []

    def publish(self, update: PlanningProgressUpdate) -> None:
        self.updates.append(update)


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


def _running_response(job_id: str) -> TravelPlanResponse:
    now = now_timepoint()
    return TravelPlanResponse(
        request_id=f"req_{job_id}",
        trace_id=f"trace_{job_id}",
        correlation_id=f"corr_{job_id}",
        idempotency_key=f"idem_{job_id}",
        planning_status=PlanningStatus.RUNNING,
        progress=15,
        travel_request=_request(f"req_{job_id}"),
        destination_presentation=None,
        plans=[],
        recommendation_result=None,
        source_failures=[],
        missing_components=[],
        blocked_plan_types=[],
        missing_plan_explanations=[],
        user_visible_warnings=[],
        async_job=AsyncJob(
            job_id=job_id,
            job_status=AsyncJobStatus.RUNNING,
            created_at=now,
            updated_at=now,
            polling_url=f"/api/travel/jobs/{job_id}",
        ),
        generated_at=now,
    )


def test_planner_publishes_only_complete_candidate_safe_plans_before_final_recommendation():
    request_id = f"req_progress_{uuid4().hex[:8]}"
    context = RequestContext(
        request_id=request_id,
        trace_id=f"trace_{request_id}",
        correlation_id=f"corr_{request_id}",
        idempotency_key=f"idem_{request_id}",
    )
    sink = _CollectingProgressSink()
    execution_metrics = PlanningExecutionMetrics()

    final = plan_trip(
        _request(request_id),
        context,
        progress_sink=sink,
        execution_metrics=execution_metrics,
    )

    assert sink.updates
    assert sink.updates[0].progress < final.progress
    assert all(update.plans for update in sink.updates)
    assert all(
        plan.recommendation_eligibility == RecommendationEligibility.ELIGIBLE
        and plan.can_be_selected_by_llm
        and plan.risk_assessment.recommendation_allowed
        for update in sink.updates
        for plan in update.plans
    )
    assert {plan.plan_id for plan in sink.updates[0].plans}.issubset({plan.plan_id for plan in final.plans})
    assert execution_metrics.route_cache_misses > 0
    assert execution_metrics.route_cache_hits > 0
    assert execution_metrics.location_cache_misses > 0
    assert execution_metrics.location_cache_hits > 0
    summary = execution_metrics.safe_summary()
    assert summary["stage_elapsed_ms"]["first_plan_built"] >= 0
    assert summary["stage_elapsed_ms"]["candidate_finalize"] >= summary["stage_elapsed_ms"]["first_plan_built"]
    assert summary["provider_request_count"] > 0
    assert "raw_user_input" not in str(summary)


def test_generation_guard_rejects_lower_progress_and_cancelled_job_overwrite():
    job_id = f"job_generation_{uuid4().hex[:8]}"
    running = _running_response(job_id)
    generation = begin_async_job(running)

    progressed = running.model_copy(update={"progress": 65})
    assert save_async_job_response_if_current(progressed, generation)
    assert not save_async_job_response_if_current(running, generation)

    invalidate_async_job_generation(job_id)
    cancelled_job = progressed.async_job.model_copy(update={"job_status": AsyncJobStatus.CANCELLED})
    cancelled = progressed.model_copy(
        update={
            "planning_status": PlanningStatus.FAILED,
            "progress": 100,
            "async_job": cancelled_job,
        }
    )
    save_async_job_response(cancelled)

    completed_job = progressed.async_job.model_copy(update={"job_status": AsyncJobStatus.COMPLETE})
    stale_completed = progressed.model_copy(
        update={
            "planning_status": PlanningStatus.COMPLETE,
            "progress": 100,
            "async_job": completed_job,
        }
    )
    assert not save_async_job_response_if_current(stale_completed, generation)
    assert get_async_job_response(job_id).async_job.job_status == AsyncJobStatus.CANCELLED
