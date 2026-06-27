from __future__ import annotations

from time import perf_counter
from uuid import uuid4

import httpx

from app.data_sources.llm_providers import LLMProviderError, build_enabled_llm_provider
from app.llm.logs import log_llm_call, stable_hash
from app.llm.prompt_versions import RECOMMENDATION_PROMPT_VERSION, REPAIR_PROMPT_VERSION
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

RECOMMENDABLE_LIFECYCLE_STATUSES = {
    PlanLifecycleStatus.GENERATED,
    PlanLifecycleStatus.PARTIALLY_VERIFIED,
    PlanLifecycleStatus.VERIFIED,
}


def eligible_plans(plans: list[TravelPlan]) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if plan.can_be_selected_by_llm
        and plan.recommendation_eligibility == RecommendationEligibility.ELIGIBLE
        and plan.plan_lifecycle_status in RECOMMENDABLE_LIFECYCLE_STATUSES
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
            if plan.recommendation_eligibility != RecommendationEligibility.ELIGIBLE:
                reasons.append(f"plan_id {slot.plan_id} is not ELIGIBLE")
            if plan.plan_lifecycle_status not in RECOMMENDABLE_LIFECYCLE_STATUSES:
                reasons.append(f"plan_id {slot.plan_id} is not active")
    return reasons


def _result(output: LLMRecommendationOutput, *, invalid_reasons: list[str], repair_attempted: bool, repair_success: bool | None, final_strategy: str, llm_call_id: str, prompt_version: str, model_name: str | None, latency_ms: int) -> RecommendationResult:
    return RecommendationResult(
        recommendation_id=f"rec_{uuid4().hex[:10]}",
        recommendation_source=RecommendationSource.LLM,
        recommendations=output.selected_recommendations,
        llm_validation_result=LLMValidationResult(
            schema_valid=True,
            semantic_valid=not invalid_reasons,
            repair_attempted=repair_attempted,
            final_strategy=final_strategy,
            invalid_reasons=invalid_reasons,
            repair_success=repair_success,
            llm_call_id=llm_call_id,
            prompt_version=prompt_version,
            model_name=model_name,
            latency_ms=latency_ms,
        ),
    )


def recommend_with_validation(llm_input: LLMRecommendationInput) -> RecommendationResult | None:
    provider = build_enabled_llm_provider()
    if provider is None:
        return None
    llm_call_id = f"llm_{uuid4().hex[:10]}"
    started = perf_counter()
    try:
        output = provider.recommend(llm_input)
    except ValueError as exc:
        latency_ms = int((perf_counter() - started) * 1000)
        invalid = [f"schema validation failed: {exc}"]
        repair_started = perf_counter()
        try:
            repaired = provider.repair_recommendation(llm_input, invalid)
        except (AttributeError, httpx.HTTPError, LLMProviderError, ValueError) as repair_exc:
            repair_latency_ms = int((perf_counter() - repair_started) * 1000)
            log_llm_call(
                llm_call_id=llm_call_id,
                request_id=llm_input.request_id,
                prompt_version=REPAIR_PROMPT_VERSION,
                model_name=getattr(provider, "model_name", None),
                input_hash=stable_hash(llm_input.model_dump_json()),
                output_hash=None,
                schema_validation_result=False,
                semantic_validation_result=False,
                repair_attempted=True,
                final_strategy="REJECTED",
                latency_ms=latency_ms + repair_latency_ms,
                invalid_reasons=invalid,
                error=str(repair_exc),
            )
            return None
        repair_latency_ms = int((perf_counter() - repair_started) * 1000)
        repaired_invalid = validate_llm_output(repaired, llm_input)
        log_llm_call(
            llm_call_id=llm_call_id,
            request_id=llm_input.request_id,
            prompt_version=REPAIR_PROMPT_VERSION,
            model_name=getattr(provider, "model_name", None),
            input_hash=stable_hash(llm_input.model_dump_json()),
            output_hash=stable_hash(repaired.model_dump_json()),
            schema_validation_result=not repaired_invalid,
            semantic_validation_result=not repaired_invalid,
            repair_attempted=True,
            final_strategy="REPAIRED" if not repaired_invalid else "REJECTED",
            latency_ms=latency_ms + repair_latency_ms,
            invalid_reasons=invalid + repaired_invalid,
        )
        if repaired_invalid:
            return None
        return _result(repaired, invalid_reasons=invalid, repair_attempted=True, repair_success=True, final_strategy="REPAIRED", llm_call_id=llm_call_id, prompt_version=REPAIR_PROMPT_VERSION, model_name=getattr(provider, "model_name", None), latency_ms=latency_ms + repair_latency_ms)
    except (httpx.HTTPError, LLMProviderError) as exc:
        latency_ms = int((perf_counter() - started) * 1000)
        log_llm_call(
            llm_call_id=llm_call_id,
            request_id=llm_input.request_id,
            prompt_version=RECOMMENDATION_PROMPT_VERSION,
            model_name=getattr(provider, "model_name", None),
            input_hash=stable_hash(llm_input.model_dump_json()),
            output_hash=None,
            schema_validation_result=False,
            semantic_validation_result=False,
            repair_attempted=False,
            final_strategy="REJECTED",
            latency_ms=latency_ms,
            error=str(exc),
        )
        return None
    latency_ms = int((perf_counter() - started) * 1000)
    invalid = validate_llm_output(output, llm_input)
    if not invalid:
        log_llm_call(
            llm_call_id=llm_call_id,
            request_id=llm_input.request_id,
            prompt_version=RECOMMENDATION_PROMPT_VERSION,
            model_name=getattr(provider, "model_name", None),
            input_hash=stable_hash(llm_input.model_dump_json()),
            output_hash=stable_hash(output.model_dump_json()),
            schema_validation_result=True,
            semantic_validation_result=True,
            repair_attempted=False,
            final_strategy="USE_ORIGINAL",
            latency_ms=latency_ms,
        )
        return _result(output, invalid_reasons=[], repair_attempted=False, repair_success=None, final_strategy="USE_ORIGINAL", llm_call_id=llm_call_id, prompt_version=RECOMMENDATION_PROMPT_VERSION, model_name=getattr(provider, "model_name", None), latency_ms=latency_ms)

    repair_started = perf_counter()
    try:
        repaired = provider.repair_recommendation(llm_input, invalid)
    except (AttributeError, httpx.HTTPError, LLMProviderError, ValueError) as exc:
        repair_latency_ms = int((perf_counter() - repair_started) * 1000)
        log_llm_call(
            llm_call_id=llm_call_id,
            request_id=llm_input.request_id,
            prompt_version=REPAIR_PROMPT_VERSION,
            model_name=getattr(provider, "model_name", None),
            input_hash=stable_hash(llm_input.model_dump_json()),
            output_hash=stable_hash(output.model_dump_json()),
            schema_validation_result=True,
            semantic_validation_result=False,
            repair_attempted=True,
            final_strategy="REJECTED",
            latency_ms=latency_ms + repair_latency_ms,
            invalid_reasons=invalid,
            error=str(exc),
        )
        return None
    repair_latency_ms = int((perf_counter() - repair_started) * 1000)
    repaired_invalid = validate_llm_output(repaired, llm_input)
    log_llm_call(
        llm_call_id=llm_call_id,
        request_id=llm_input.request_id,
        prompt_version=REPAIR_PROMPT_VERSION,
        model_name=getattr(provider, "model_name", None),
        input_hash=stable_hash(llm_input.model_dump_json()),
        output_hash=stable_hash(repaired.model_dump_json()),
        schema_validation_result=True,
        semantic_validation_result=not repaired_invalid,
        repair_attempted=True,
        final_strategy="REPAIRED" if not repaired_invalid else "REJECTED",
        latency_ms=latency_ms + repair_latency_ms,
        invalid_reasons=invalid + repaired_invalid,
    )
    if repaired_invalid:
        return None
    return _result(repaired, invalid_reasons=invalid, repair_attempted=True, repair_success=True, final_strategy="REPAIRED", llm_call_id=llm_call_id, prompt_version=REPAIR_PROMPT_VERSION, model_name=getattr(provider, "model_name", None), latency_ms=latency_ms + repair_latency_ms)
