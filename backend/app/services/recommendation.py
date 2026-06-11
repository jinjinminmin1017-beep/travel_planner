from __future__ import annotations

from uuid import uuid4

import httpx

from app.data_sources.llm_providers import LLMProviderError, build_enabled_llm_provider
from app.models.schemas import (
    LLMRecommendationInput,
    LLMRecommendationOutput,
    LLMValidationResult,
    PlanLifecycleStatus,
    RecommendationEligibility,
    RecommendationResult,
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


def recommend_with_validation(llm_input: LLMRecommendationInput) -> RecommendationResult | None:
    provider = build_enabled_llm_provider()
    if provider is None:
        return None
    try:
        output = provider.recommend(llm_input)
    except (httpx.HTTPError, LLMProviderError, ValueError):
        return None
    invalid = validate_llm_output(output, llm_input)
    if not invalid:
        return RecommendationResult(
            recommendation_id=f"rec_{uuid4().hex[:10]}",
            recommendation_source=RecommendationSource.LLM,
            recommendations=output.selected_recommendations,
            llm_validation_result=LLMValidationResult(
                schema_valid=True,
                semantic_valid=True,
                repair_attempted=False,
                final_strategy="USE_ORIGINAL",
                invalid_reasons=[],
            ),
        )

    return None
