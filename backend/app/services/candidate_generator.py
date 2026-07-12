from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import (
    MissingPlanExplanation,
    PlanLifecycleStatus,
    PlanType,
    RecommendationEligibility,
    RiskLevel,
    TravelPlan,
    TravelRequest,
)
from app.services.constraints.evaluator import evaluate_plan_constraints
from app.services.constraints.models import ConstraintEvaluationResult

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
    constraint_evaluations: list[ConstraintEvaluationResult]


def generate_candidate_plan_pool(
    plans: list[TravelPlan],
    travel_request: TravelRequest,
    existing_explanations: list[MissingPlanExplanation] | None = None,
    limit: int = 15,
) -> CandidateGenerationResult:
    explanations = list(existing_explanations or [])
    warnings: list[str] = []
    candidates: list[TravelPlan] = []
    evaluations: list[ConstraintEvaluationResult] = []
    for plan in plans:
        if not _is_recommendable(plan):
            continue
        evaluation = evaluate_plan_constraints(plan, travel_request)
        evaluations.append(evaluation)
        if not evaluation.satisfies_all:
            explanations.extend(
                MissingPlanExplanation(plan_type=plan.plan_type, reason_code=item.reason_code, user_visible_message=item.user_visible_message)
                for item in evaluation.violations
            )
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
        constraint_evaluations=evaluations,
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


def _sort_by_preferences(plans: list[TravelPlan], travel_request: TravelRequest) -> list[TravelPlan]:
    soft = travel_request.soft_preferences
    if soft.prefer_low_cost:
        return sorted(plans, key=lambda plan: (plan.cost_breakdown.total_cost.amount_minor, -plan.comfort_score.total_score))
    if soft.prefer_comfort:
        return sorted(plans, key=lambda plan: (-plan.comfort_score.total_score, plan.cost_breakdown.total_cost.amount_minor))
    return plans
