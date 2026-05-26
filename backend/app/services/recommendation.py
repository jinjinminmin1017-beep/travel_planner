from __future__ import annotations

from uuid import uuid4

from app.models.schemas import (
    LLMRecommendationInput,
    LLMRecommendationOutput,
    LLMValidationResult,
    PlanLifecycleStatus,
    RecommendationEligibility,
    RecommendationResult,
    RecommendationSlot,
    RecommendationSlotStatus,
    RecommendationSource,
    RecommendationType,
    RiskLevel,
    TravelPlan,
)


def eligible_plans(plans: list[TravelPlan]) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if plan.can_be_selected_by_llm
        and plan.recommendation_eligibility == RecommendationEligibility.ELIGIBLE
        and plan.plan_lifecycle_status == PlanLifecycleStatus.ACTIVE
        and plan.risk_assessment.overall_risk_level != RiskLevel.BLOCKED
    ]


def validate_llm_output(output: LLMRecommendationOutput, llm_input: LLMRecommendationInput) -> list[str]:
    reasons: list[str] = []
    expected = {RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED}
    actual = {RecommendationType(slot.recommendation_type) for slot in output.selected_recommendations}
    if actual != expected:
        reasons.append("recommendation slots must be CHEAPEST, MOST_COMFORTABLE, BALANCED")

    candidate_ids = set(llm_input.candidate_plan_ids)
    candidate_by_id = {plan.plan_id: plan for plan in llm_input.candidate_plans}
    if candidate_ids != set(candidate_by_id):
        reasons.append("candidate_plan_ids must match candidate_plans")

    for slot in output.selected_recommendations:
        if slot.status == RecommendationSlotStatus.AVAILABLE:
            if slot.plan_id not in candidate_ids:
                reasons.append(f"plan_id {slot.plan_id} is not in candidate_plan_ids")
                continue
            plan = candidate_by_id[slot.plan_id]
            if not plan.can_be_selected_by_llm:
                reasons.append(f"plan_id {slot.plan_id} cannot be selected by LLM")
            if plan.recommendation_eligibility == RecommendationEligibility.BLOCKED:
                reasons.append(f"plan_id {slot.plan_id} is BLOCKED")
            if plan.plan_lifecycle_status in {PlanLifecycleStatus.EXPIRED, PlanLifecycleStatus.INVALIDATED}:
                reasons.append(f"plan_id {slot.plan_id} is not active")
    return reasons


class MockLLMProvider:
    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
        if "force_invalid_llm" in llm_input.travel_request.raw_user_input:
            return LLMRecommendationOutput(
                selected_recommendations=[
                    RecommendationSlot(
                        recommendation_type=RecommendationType.CHEAPEST,
                        status=RecommendationSlotStatus.AVAILABLE,
                        plan_id="missing_plan",
                        reason="Deliberately invalid mock output.",
                    ),
                    RecommendationSlot(
                        recommendation_type=RecommendationType.MOST_COMFORTABLE,
                        status=RecommendationSlotStatus.AVAILABLE,
                        plan_id=llm_input.candidate_plan_ids[0],
                        reason="Invalid output used for repair/fallback testing.",
                    ),
                    RecommendationSlot(
                        recommendation_type=RecommendationType.BALANCED,
                        status=RecommendationSlotStatus.AVAILABLE,
                        plan_id=llm_input.candidate_plan_ids[0],
                        reason="Invalid output used for repair/fallback testing.",
                    ),
                ],
                validation_blockers=[],
                explanation="Invalid mock output.",
            )
        return deterministic_recommend(llm_input.candidate_plans, source=RecommendationSource.MOCK_LLM).to_llm_output()


def _slot(recommendation_type: RecommendationType, plan: TravelPlan | None, reason: str) -> RecommendationSlot:
    if plan is None:
        return RecommendationSlot(
            recommendation_type=recommendation_type,
            status=RecommendationSlotStatus.NOT_AVAILABLE,
            plan_id=None,
            reason=reason,
        )
    return RecommendationSlot(
        recommendation_type=recommendation_type,
        status=RecommendationSlotStatus.AVAILABLE,
        plan_id=plan.plan_id,
        reason=reason,
    )


class _RecommendationBuild:
    def __init__(self, result: RecommendationResult):
        self.result = result

    def to_llm_output(self) -> LLMRecommendationOutput:
        return LLMRecommendationOutput(
            selected_recommendations=self.result.recommendations,
            validation_blockers=[],
            explanation="Mock LLM selected from deterministic candidate plans only.",
        )


def deterministic_recommend(plans: list[TravelPlan], source: RecommendationSource = RecommendationSource.DETERMINISTIC_FALLBACK) -> _RecommendationBuild:
    eligible = eligible_plans(plans)
    cheapest = min(eligible, key=lambda plan: plan.cost_breakdown.total_cost.amount_minor, default=None)
    comfortable = max(eligible, key=lambda plan: plan.comfort_score.total_score, default=None)

    def balanced_score(plan: TravelPlan) -> float:
        cost_component = 1 / max(plan.cost_breakdown.total_cost.amount_minor, 1)
        return plan.comfort_score.total_score * 0.35 + cost_component * 100000 * 0.25 - plan.total_duration_minutes * 0.001

    balanced_candidates = [plan for plan in eligible if plan.plan_id not in {getattr(cheapest, "plan_id", None), getattr(comfortable, "plan_id", None)}]
    balanced = max(balanced_candidates or eligible, key=balanced_score, default=None)
    recommendations = [
        _slot(
            RecommendationType.CHEAPEST,
            cheapest,
            "总费用最低，且没有被安全规则阻断。" if cheapest else "当前没有满足条件的最优惠方案。",
        ),
        _slot(
            RecommendationType.MOST_COMFORTABLE,
            comfortable,
            "舒适度评分最高，综合考虑接驳、换乘、舱位/座席和风险。" if comfortable else "当前没有满足条件的最舒适方案。",
        ),
        _slot(
            RecommendationType.BALANCED,
            balanced,
            "在费用、耗时、风险和舒适度之间取得较好平衡。" if balanced else "当前没有满足条件的综合推荐方案。",
        ),
    ]
    result = RecommendationResult(
        recommendation_id=f"rec_{uuid4().hex[:10]}",
        recommendation_source=source,
        recommendations=recommendations,
        llm_validation_result=LLMValidationResult(
            schema_valid=True,
            semantic_valid=True,
            repair_attempted=False,
            final_strategy="USE_ORIGINAL" if source != RecommendationSource.DETERMINISTIC_FALLBACK else "DETERMINISTIC_FALLBACK",
            invalid_reasons=[],
        ),
    )
    return _RecommendationBuild(result)


def recommend_with_validation(llm_input: LLMRecommendationInput) -> RecommendationResult:
    provider = MockLLMProvider()
    output = provider.recommend(llm_input)
    invalid = validate_llm_output(output, llm_input)
    if not invalid:
        return RecommendationResult(
            recommendation_id=f"rec_{uuid4().hex[:10]}",
            recommendation_source=RecommendationSource.MOCK_LLM,
            recommendations=output.selected_recommendations,
            llm_validation_result=LLMValidationResult(
                schema_valid=True,
                semantic_valid=True,
                repair_attempted=False,
                final_strategy="USE_ORIGINAL",
                invalid_reasons=[],
            ),
        )

    fallback = deterministic_recommend(llm_input.candidate_plans).result
    fallback.llm_validation_result = LLMValidationResult(
        schema_valid=True,
        semantic_valid=False,
        repair_attempted=True,
        final_strategy="DETERMINISTIC_FALLBACK",
        invalid_reasons=invalid,
    )
    return fallback
