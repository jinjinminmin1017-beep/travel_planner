from __future__ import annotations

from copy import deepcopy

from app.core.context import RequestContext
from app.models.schemas import (
    LLMRecommendationInput,
    PreferenceApplication,
    RailSegment,
    RecommendationEligibility,
    RecommendationResult,
    RecommendationSlot,
    RecommendationSlotStatus,
    SeatOption,
    TravelPlan,
    TravelPlanResponse,
    now_timepoint,
)
from app.services.candidate_generator import generate_candidate_plan_pool
from app.services.cost_comfort_risk_engine import refresh_plan_cost_and_quality
from app.services.recommendation import recommend_with_validation


_SEAT_ALIASES = {
    "二等": "二等座",
    "二等座": "二等座",
    "一等": "一等座",
    "一等座": "一等座",
    "商务": "商务座",
    "商务座": "商务座",
    "特等": "特等座",
    "特等座": "特等座",
    "无座": "无座",
}
_SEAT_COMFORT_RANK = {"无座": 0, "二等座": 1, "一等座": 2, "特等座": 3, "商务座": 4}


def apply_rail_seat_to_result_set(
    response: TravelPlanResponse,
    *,
    target_plan_id: str,
    target_segment_id: str,
    target_option_id: str,
    ctx: RequestContext,
) -> tuple[TravelPlanResponse, PreferenceApplication, TravelPlan]:
    snapshot = deepcopy(response)
    target_plan = next((plan for plan in snapshot.plans if plan.plan_id == target_plan_id), None)
    if target_plan is None:
        raise ValueError("target plan does not belong to the current result set")
    target_segment = next(
        (segment for segment in target_plan.segments if segment.segment_id == target_segment_id and isinstance(segment, RailSegment)),
        None,
    )
    if target_segment is None:
        raise ValueError("target segment does not support rail seat options")
    selected_target_option = next((option for option in target_segment.seat_options if option.option_id == target_option_id), None)
    if selected_target_option is None:
        raise ValueError("selected option_id is not available for target segment")

    canonical_value = normalize_seat_type(selected_target_option.seat_type)
    applied_plan_ids: list[str] = []
    unsupported_plan_ids: list[str] = []

    for plan in snapshot.plans:
        rail_segments = [segment for segment in plan.segments if isinstance(segment, RailSegment)]
        if not rail_segments:
            continue
        matches = [
            next((option for option in segment.seat_options if normalize_seat_type(option.seat_type) == canonical_value), None)
            for segment in rail_segments
        ]
        if any(option is None for option in matches):
            plan.recommendation_eligibility = RecommendationEligibility.NOT_RECOMMENDED
            plan.can_be_selected_by_llm = False
            plan.block_reason_code = "RAIL_SEAT_UNSUPPORTED"
            plan.block_reason_message = f"该方案并非所有铁路段都提供{canonical_value}，已退出当前推荐。"
            unsupported_plan_ids.append(plan.plan_id)
            continue
        _apply_plan_seat_options(plan, rail_segments, matches)
        applied_plan_ids.append(plan.plan_id)

    snapshot.travel_request.preferred_rail_seat = canonical_value
    snapshot.travel_request.preference_source = "USER_EXPLICIT"
    candidate_pool = generate_candidate_plan_pool(snapshot.plans, snapshot.travel_request, snapshot.missing_plan_explanations)
    snapshot.recommendation_result = _refresh_recommendations(snapshot, candidate_pool.llm_candidate_plans, ctx)
    snapshot.generated_at = now_timepoint()
    snapshot = TravelPlanResponse.model_validate(snapshot.model_dump())

    updated_target = next(plan for plan in snapshot.plans if plan.plan_id == target_plan_id)
    message = f"{canonical_value}已应用到{len(applied_plan_ids)}个方案"
    if unsupported_plan_ids:
        message += f"；{len(unsupported_plan_ids)}个方案不提供该席别，已退出推荐。"
    else:
        message += "。"
    application = PreferenceApplication(
        canonical_value=canonical_value,
        applied_plan_ids=applied_plan_ids,
        unsupported_plan_ids=unsupported_plan_ids,
        message=message,
    )
    return snapshot, application, updated_target


def normalize_seat_type(value: str) -> str:
    normalized = "".join(value.strip().split()).replace("席", "座")
    return _SEAT_ALIASES.get(normalized, normalized)


def _apply_plan_seat_options(plan: TravelPlan, segments: list[RailSegment], matches: list[SeatOption | None]) -> None:
    comfort_delta = 0.0
    for segment, selected_option in zip(segments, matches, strict=True):
        assert selected_option is not None
        previous = next(option for option in segment.seat_options if option.option_id == segment.selected_seat_option_id)
        previous_rank = _SEAT_COMFORT_RANK.get(normalize_seat_type(previous.seat_type), 1)
        selected_rank = _SEAT_COMFORT_RANK.get(normalize_seat_type(selected_option.seat_type), previous_rank)
        comfort_delta += (selected_rank - previous_rank) * 0.8
        segment.selected_seat_option_id = selected_option.option_id
    plan.comfort_score.total_score = round(max(0, min(10, plan.comfort_score.total_score + comfort_delta)), 2)
    if "座席/舱位舒适度" in plan.comfort_score.breakdown:
        current = plan.comfort_score.breakdown["座席/舱位舒适度"]
        plan.comfort_score.breakdown["座席/舱位舒适度"] = round(max(0, min(10, current + comfort_delta)), 2)
    refresh_plan_cost_and_quality(plan)


def _refresh_recommendations(
    response: TravelPlanResponse,
    candidates: list[TravelPlan],
    ctx: RequestContext,
) -> RecommendationResult | None:
    refreshed = None
    if candidates:
        refreshed = recommend_with_validation(
            LLMRecommendationInput(
                request_id=ctx.request_id,
                travel_request=response.travel_request,
                candidate_plan_ids=[plan.plan_id for plan in candidates],
                candidate_plans=candidates,
            )
        )
    if refreshed is not None:
        return refreshed
    return _sanitize_existing_recommendations(response.recommendation_result, {plan.plan_id for plan in candidates})


def _sanitize_existing_recommendations(
    recommendation: RecommendationResult | None,
    eligible_plan_ids: set[str],
) -> RecommendationResult | None:
    if recommendation is None:
        return None
    slots: list[RecommendationSlot] = []
    for slot in recommendation.recommendations:
        if slot.status == RecommendationSlotStatus.AVAILABLE and slot.plan_id not in eligible_plan_ids:
            slots.append(
                slot.model_copy(
                    update={
                        "status": RecommendationSlotStatus.NOT_AVAILABLE,
                        "plan_id": None,
                        "reason": "当前席别下暂无符合条件的可推荐方案。",
                    }
                )
            )
        else:
            slots.append(slot)
    return recommendation.model_copy(update={"recommendations": slots})
