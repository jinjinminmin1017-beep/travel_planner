from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import (
    FlightSegment,
    MissingPlanExplanation,
    PlanLifecycleStatus,
    PlanType,
    RailSegment,
    RecommendationEligibility,
    RiskLevel,
    TimePoint,
    TransportMode,
    TravelPlan,
    TravelRequest,
)

RECOMMENDABLE_LIFECYCLE_STATUSES = {
    PlanLifecycleStatus.GENERATED,
    PlanLifecycleStatus.PARTIALLY_VERIFIED,
    PlanLifecycleStatus.VERIFIED,
}


@dataclass(frozen=True)
class CandidateGenerationResult:
    raw_plans: list[TravelPlan]
    llm_candidate_plans: list[TravelPlan]
    missing_plan_explanations: list[MissingPlanExplanation]
    user_visible_warnings: list[str]


def generate_candidate_plan_pool(
    plans: list[TravelPlan],
    travel_request: TravelRequest,
    existing_explanations: list[MissingPlanExplanation] | None = None,
    limit: int = 15,
) -> CandidateGenerationResult:
    explanations = list(existing_explanations or [])
    warnings: list[str] = []
    candidates: list[TravelPlan] = []
    for plan in plans:
        if not _is_recommendable(plan):
            continue
        hard_reason = _hard_constraint_reason(plan, travel_request)
        if hard_reason:
            explanations.append(MissingPlanExplanation(plan_type=plan.plan_type, reason_code=hard_reason[0], user_visible_message=hard_reason[1]))
            continue
        soft_reason = _soft_preference_exclusion_reason(plan, travel_request)
        if soft_reason:
            explanations.append(MissingPlanExplanation(plan_type=plan.plan_type, reason_code=soft_reason[0], user_visible_message=soft_reason[1]))
            continue
        candidates.append(plan)

    candidates = _sort_by_preferences(candidates, travel_request)[:limit]
    if len(candidates) < 5:
        warnings.append("满足当前约束的 LLM 候选方案少于 5 条，系统将仅使用可验证候选，不补造方案。")
    return CandidateGenerationResult(
        raw_plans=plans,
        llm_candidate_plans=candidates,
        missing_plan_explanations=explanations,
        user_visible_warnings=warnings,
    )


def candidate_plans_for_recommendation(plans: list[TravelPlan], limit: int = 15) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if _is_recommendable(plan)
    ][:limit]


def _is_recommendable(plan: TravelPlan) -> bool:
    return (
        plan.can_be_selected_by_llm
        and plan.recommendation_eligibility == RecommendationEligibility.ELIGIBLE
        and plan.plan_lifecycle_status in RECOMMENDABLE_LIFECYCLE_STATUSES
        and plan.risk_assessment.overall_risk_level != RiskLevel.BLOCKED
    )


def _hard_constraint_reason(plan: TravelPlan, travel_request: TravelRequest) -> tuple[str, str] | None:
    modes = _main_transport_modes(plan)
    allowed = set(travel_request.hard_constraints.allowed_transport_modes)
    excluded = set(travel_request.hard_constraints.excluded_transport_modes)
    if allowed and not modes.issubset(allowed):
        return ("HARD_CONSTRAINT_TRANSPORT_MODE_NOT_ALLOWED", f"{plan.plan_name} 包含当前不允许的交通方式，未进入推荐候选池。")
    blocked_modes = modes & excluded
    if blocked_modes:
        mode_names = "、".join(mode.value for mode in blocked_modes)
        return ("HARD_CONSTRAINT_TRANSPORT_MODE_EXCLUDED", f"{plan.plan_name} 包含已排除的交通方式（{mode_names}），未进入推荐候选池。")
    max_cost = travel_request.hard_constraints.max_total_cost
    if max_cost and plan.cost_breakdown.total_cost.amount_minor > max_cost.amount_minor:
        return ("HARD_CONSTRAINT_MAX_TOTAL_COST", f"{plan.plan_name} 超出预算上限，未进入推荐候选池。")
    latest_arrival = travel_request.hard_constraints.latest_arrival_time or travel_request.latest_arrival_time
    plan_arrival = _plan_main_arrival_time(plan)
    if latest_arrival and plan_arrival and plan_arrival.datetime > latest_arrival.datetime:
        return ("HARD_CONSTRAINT_LATEST_ARRIVAL", f"{plan.plan_name} 晚于最晚到达时间，未进入推荐候选池。")
    earliest_departure = travel_request.hard_constraints.earliest_departure_time or travel_request.earliest_departure_time
    plan_departure = _plan_main_departure_time(plan)
    if earliest_departure and plan_departure and plan_departure.datetime < earliest_departure.datetime:
        return ("HARD_CONSTRAINT_EARLIEST_DEPARTURE", f"{plan.plan_name} 早于最早出发时间，未进入推荐候选池。")
    return None


def _soft_preference_exclusion_reason(plan: TravelPlan, travel_request: TravelRequest) -> tuple[str, str] | None:
    soft = travel_request.soft_preferences
    if not soft.accept_rail_transfer and plan.plan_type in {PlanType.TRANSFER_RAIL, PlanType.MULTI_TRANSFER_RAIL}:
        return ("SOFT_PREFERENCE_RAIL_TRANSFER_DECLINED", f"{plan.plan_name} 包含铁路中转，未进入推荐候选池。")
    if not soft.accept_flight_transfer and plan.plan_type in {PlanType.TRANSFER_FLIGHT, PlanType.MULTI_AIRPORT_FLIGHT}:
        return ("SOFT_PREFERENCE_FLIGHT_TRANSFER_DECLINED", f"{plan.plan_name} 包含航班中转或多机场组合，未进入推荐候选池。")
    if not soft.accept_mixed_transport and plan.plan_type in {PlanType.FLIGHT_RAIL_MIXED, PlanType.MIXED}:
        return ("SOFT_PREFERENCE_MIXED_TRANSPORT_DECLINED", f"{plan.plan_name} 包含跨交通方式组合，未进入推荐候选池。")
    if not soft.accept_ticket_enhancement and plan.plan_type == PlanType.RAIL_TICKET_ENHANCEMENT:
        return ("SOFT_PREFERENCE_TICKET_ENHANCEMENT_DECLINED", f"{plan.plan_name} 包含票源增强，未进入推荐候选池。")
    return None


def _sort_by_preferences(plans: list[TravelPlan], travel_request: TravelRequest) -> list[TravelPlan]:
    soft = travel_request.soft_preferences
    if soft.prefer_low_cost:
        return sorted(plans, key=lambda plan: (plan.cost_breakdown.total_cost.amount_minor, -plan.comfort_score.total_score))
    if soft.prefer_comfort:
        return sorted(plans, key=lambda plan: (-plan.comfort_score.total_score, plan.cost_breakdown.total_cost.amount_minor))
    return plans


def _main_transport_modes(plan: TravelPlan) -> set[TransportMode]:
    modes: set[TransportMode] = set()
    for segment in plan.segments:
        if isinstance(segment, RailSegment):
            modes.add(TransportMode.RAIL)
        elif isinstance(segment, FlightSegment):
            modes.add(TransportMode.FLIGHT)
    return modes


def _plan_main_departure_time(plan: TravelPlan) -> TimePoint | None:
    for segment in plan.segments:
        if not isinstance(segment, (RailSegment, FlightSegment)):
            continue
        departure = getattr(segment, "departure_time", None)
        if departure:
            return departure
    return None


def _plan_main_arrival_time(plan: TravelPlan) -> TimePoint | None:
    arrivals = [getattr(segment, "arrival_time", None) for segment in plan.segments if isinstance(segment, (RailSegment, FlightSegment)) and getattr(segment, "arrival_time", None)]
    return arrivals[-1] if arrivals else None
