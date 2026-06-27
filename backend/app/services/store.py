from __future__ import annotations

from app.models.schemas import FeedbackResponse, RecalculateResponse, TravelPlan, TravelPlanResponse
from app.services.cache_store import async_job_ttl_seconds, get_json, recalculate_ttl_seconds, set_json
from app.services.observability import record_travel_response
from app.services.persistence import load_plan_snapshot, load_response_for_plan_snapshot, save_feedback_snapshot, save_plan_snapshot, save_travel_response

PLANS: dict[str, TravelPlan] = {}
RESPONSES: dict[str, TravelPlanResponse] = {}
PLAN_RESPONSES: dict[str, TravelPlanResponse] = {}
RECALCULATIONS: dict[tuple[str, str], RecalculateResponse] = {}
ASYNC_JOB_RESPONSES: dict[str, TravelPlanResponse] = {}
ASYNC_JOB_BY_IDEMPOTENCY: dict[str, str] = {}
FEEDBACKS: list[FeedbackResponse] = []
FEEDBACK_COUNTS: dict[tuple[str, str | None], int] = {}


def _index_response(response: TravelPlanResponse) -> None:
    RESPONSES[response.request_id] = response
    for plan in response.plans:
        PLANS[plan.plan_id] = plan
        PLAN_RESPONSES[plan.plan_id] = response


def save_response(response: TravelPlanResponse) -> None:
    _index_response(response)
    save_travel_response(response)
    record_travel_response(response)


def save_async_job_response(response: TravelPlanResponse) -> None:
    if response.async_job is None:
        raise ValueError("async_job is required to save async job response")
    ASYNC_JOB_RESPONSES[response.async_job.job_id] = response
    ASYNC_JOB_BY_IDEMPOTENCY[response.idempotency_key] = response.async_job.job_id
    set_json(f"async_job:{response.async_job.job_id}", response.model_dump_json(), async_job_ttl_seconds())
    _index_response(response)
    save_travel_response(response)
    if response.planning_status not in {"PENDING", "RUNNING"}:
        record_travel_response(response)


def get_async_job_response(job_id: str) -> TravelPlanResponse | None:
    cached = ASYNC_JOB_RESPONSES.get(job_id)
    if cached is not None:
        return cached
    cached_json = get_json(f"async_job:{job_id}")
    if cached_json:
        response = TravelPlanResponse.model_validate_json(cached_json)
        ASYNC_JOB_RESPONSES[job_id] = response
        return response
    return None


def get_async_job_by_idempotency(idempotency_key: str) -> TravelPlanResponse | None:
    job_id = ASYNC_JOB_BY_IDEMPOTENCY.get(idempotency_key)
    if job_id is None:
        return None
    return get_async_job_response(job_id)


def get_plan(plan_id: str) -> TravelPlan | None:
    plan = PLANS.get(plan_id)
    if plan is not None:
        return plan
    plan = load_plan_snapshot(plan_id)
    if plan is not None:
        PLANS[plan_id] = plan
    return plan


def get_response_for_plan(plan_id: str) -> TravelPlanResponse | None:
    response = PLAN_RESPONSES.get(plan_id)
    if response is not None:
        return response
    response = load_response_for_plan_snapshot(plan_id)
    if response is not None:
        PLAN_RESPONSES[plan_id] = response
    return response


def update_plan(plan: TravelPlan) -> None:
    PLANS[plan.plan_id] = plan
    save_plan_snapshot(plan)


def get_recalculate_response(plan_id: str, idempotency_key: str) -> RecalculateResponse | None:
    cached = RECALCULATIONS.get((plan_id, idempotency_key))
    if cached is not None:
        return cached
    cached_json = get_json(f"recalculate:{plan_id}:{idempotency_key}")
    if cached_json:
        response = RecalculateResponse.model_validate_json(cached_json)
        RECALCULATIONS[(plan_id, idempotency_key)] = response
        return response
    return None


def save_recalculate_response(response: RecalculateResponse) -> None:
    RECALCULATIONS[(response.plan.plan_id, response.idempotency_key)] = response
    set_json(f"recalculate:{response.plan.plan_id}:{response.idempotency_key}", response.model_dump_json(), recalculate_ttl_seconds())


def save_feedback(response: FeedbackResponse) -> FeedbackResponse:
    FEEDBACKS.append(response)
    key = (response.category, response.source_id)
    FEEDBACK_COUNTS[key] = FEEDBACK_COUNTS.get(key, 0) + 1
    response.category_count = FEEDBACK_COUNTS[key]
    save_feedback_snapshot(response)
    return response
