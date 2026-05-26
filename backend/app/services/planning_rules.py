from __future__ import annotations

from app.models.schemas import (
    FlightSegment,
    LocalTransferSegment,
    PlanLifecycleStatus,
    RecommendationEligibility,
    RiskLevel,
    TravelPlan,
)


def candidate_plans_for_recommendation(plans: list[TravelPlan], limit: int = 15) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if plan.can_be_selected_by_llm
        and plan.recommendation_eligibility == RecommendationEligibility.ELIGIBLE
        and plan.plan_lifecycle_status == PlanLifecycleStatus.ACTIVE
        and plan.risk_assessment.overall_risk_level != RiskLevel.BLOCKED
    ][:limit]


def blocked_or_backup_plans(plans: list[TravelPlan]) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if not plan.can_be_selected_by_llm
        or plan.recommendation_eligibility != RecommendationEligibility.ELIGIBLE
        or plan.risk_assessment.overall_risk_level == RiskLevel.BLOCKED
    ]


def option_ids_for_segment(segment: object) -> set[str]:
    if hasattr(segment, "seat_options"):
        return {item.option_id for item in segment.seat_options}
    if hasattr(segment, "cabin_options"):
        return {item.option_id for item in segment.cabin_options}
    if isinstance(segment, LocalTransferSegment):
        return set(segment.available_options)
    return set()


def assert_option_available(segment: object, option_id: str) -> None:
    if option_id not in option_ids_for_segment(segment):
        raise ValueError("selected option is not available on target segment")


def has_auxiliary_flight_gap(plan: TravelPlan) -> bool:
    return any(isinstance(segment, FlightSegment) and not segment.previous_flight_risk_available for segment in plan.segments)
