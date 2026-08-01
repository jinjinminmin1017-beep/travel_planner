from __future__ import annotations

import os
from time import perf_counter
from uuid import uuid4

import httpx

from app.data_sources.llm_providers import LLMProviderError, build_enabled_llm_provider
from app.llm.logs import log_llm_call, stable_hash
from app.llm.prompt_versions import RECOMMENDATION_PROMPT_VERSION, REPAIR_PROMPT_VERSION
from app.models.schemas import (
    FlightSegment,
    LLMRecommendationInput,
    LLMRecommendationOutput,
    LLMValidationResult,
    PlanLifecycleStatus,
    RailSegment,
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


def validate_llm_output(
    output: LLMRecommendationOutput,
    llm_input: LLMRecommendationInput,
    *,
    enforce_deterministic_semantics: bool = True,
) -> list[str]:
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
    recommendable = eligible_plans(llm_input.candidate_plans)
    if recommendable and enforce_deterministic_semantics:
        expected_cheapest = deterministic_cheapest_plan(recommendable).plan_id
        expected_comfort = deterministic_most_comfortable_plan(recommendable).plan_id
        slots_by_type = {
            RecommendationType(slot.recommendation_type): slot
            for slot in output.selected_recommendations
        }
        cheapest_slot = slots_by_type.get(RecommendationType.CHEAPEST)
        if cheapest_slot and (
            cheapest_slot.status != RecommendationSlotStatus.AVAILABLE
            or cheapest_slot.plan_id != expected_cheapest
        ):
            reasons.append(
                f"CHEAPEST must select deterministic plan_id {expected_cheapest}"
            )
        comfort_slot = slots_by_type.get(RecommendationType.MOST_COMFORTABLE)
        if comfort_slot and (
            comfort_slot.status != RecommendationSlotStatus.AVAILABLE
            or comfort_slot.plan_id != expected_comfort
        ):
            reasons.append(
                f"MOST_COMFORTABLE must select deterministic plan_id {expected_comfort}"
            )
        balanced_slot = slots_by_type.get(RecommendationType.BALANCED)
        pareto_ids = {plan.plan_id for plan in pareto_candidate_plans(recommendable)}
        if (
            balanced_slot
            and balanced_slot.status == RecommendationSlotStatus.AVAILABLE
            and balanced_slot.plan_id in candidate_ids
            and balanced_slot.plan_id not in pareto_ids
        ):
            reasons.append(
                f"BALANCED plan_id {balanced_slot.plan_id} is outside the deterministic Pareto set"
            )
    return reasons


def deterministic_cheapest_plan(plans: list[TravelPlan]) -> TravelPlan:
    return min(
        plans,
        key=lambda plan: (
            plan.cost_breakdown.total_cost.amount_minor,
            plan.total_duration_minutes,
            plan.plan_id,
        ),
    )


def deterministic_most_comfortable_plan(plans: list[TravelPlan]) -> TravelPlan:
    return min(
        plans,
        key=lambda plan: (
            -plan.comfort_score.total_score,
            _risk_rank(plan.risk_assessment.overall_risk_level),
            plan.cost_breakdown.total_cost.amount_minor,
            plan.total_duration_minutes,
            plan.plan_id,
        ),
    )


def pareto_candidate_plans(plans: list[TravelPlan]) -> list[TravelPlan]:
    return [
        plan
        for plan in plans
        if not any(
            other.plan_id != plan.plan_id and _dominates(other, plan)
            for other in plans
        )
    ]


def _dominates(candidate: TravelPlan, target: TravelPlan) -> bool:
    candidate_values = (
        candidate.cost_breakdown.total_cost.amount_minor,
        candidate.total_duration_minutes,
        -candidate.comfort_score.total_score,
        _risk_rank(candidate.risk_assessment.overall_risk_level),
    )
    target_values = (
        target.cost_breakdown.total_cost.amount_minor,
        target.total_duration_minutes,
        -target.comfort_score.total_score,
        _risk_rank(target.risk_assessment.overall_risk_level),
    )
    return all(left <= right for left, right in zip(candidate_values, target_values, strict=True)) and any(
        left < right for left, right in zip(candidate_values, target_values, strict=True)
    )


def _apply_deterministic_gate(
    output: LLMRecommendationOutput,
    llm_input: LLMRecommendationInput,
) -> tuple[LLMRecommendationOutput, bool]:
    recommendable = eligible_plans(llm_input.candidate_plans)
    if not recommendable:
        return output, False
    candidate_by_id = {plan.plan_id: plan for plan in recommendable}
    cheapest = deterministic_cheapest_plan(recommendable)
    most_comfortable = deterministic_most_comfortable_plan(recommendable)
    pareto = pareto_candidate_plans(recommendable)
    balanced_fallback = min(
        pareto,
        key=lambda plan: (
            _risk_rank(plan.risk_assessment.overall_risk_level),
            plan.cost_breakdown.total_cost.amount_minor,
            plan.total_duration_minutes,
            -plan.comfort_score.total_score,
            plan.plan_id,
        ),
    )
    corrected = output.model_copy(deep=True)
    changed = False
    for slot in corrected.selected_recommendations:
        recommendation_type = RecommendationType(slot.recommendation_type)
        selected: TravelPlan | None = None
        if recommendation_type == RecommendationType.CHEAPEST:
            if slot.status != RecommendationSlotStatus.AVAILABLE or slot.plan_id in candidate_by_id:
                selected = cheapest
        elif recommendation_type == RecommendationType.MOST_COMFORTABLE:
            if slot.status != RecommendationSlotStatus.AVAILABLE or slot.plan_id in candidate_by_id:
                selected = most_comfortable
        elif recommendation_type == RecommendationType.BALANCED:
            pareto_ids = {plan.plan_id for plan in pareto}
            if slot.status != RecommendationSlotStatus.AVAILABLE:
                selected = balanced_fallback
            elif slot.plan_id in candidate_by_id and slot.plan_id not in pareto_ids:
                selected = balanced_fallback
            elif slot.plan_id in candidate_by_id:
                selected = candidate_by_id[slot.plan_id]
        if selected is None:
            continue
        new_reason = _deterministic_reason(recommendation_type, selected)
        if (
            slot.status != RecommendationSlotStatus.AVAILABLE
            or slot.plan_id != selected.plan_id
            or slot.reason != new_reason
        ):
            changed = True
        slot.status = RecommendationSlotStatus.AVAILABLE
        slot.plan_id = selected.plan_id
        slot.reason = new_reason
    return corrected, changed


def _deterministic_reason(
    recommendation_type: RecommendationType,
    plan: TravelPlan,
) -> str:
    selected_options: list[str] = []
    for segment in plan.segments:
        if isinstance(segment, RailSegment):
            option = next(
                item for item in segment.seat_options
                if item.option_id == segment.selected_seat_option_id
            )
            selected_options.append(f"{segment.train_number} {option.seat_type}")
        elif isinstance(segment, FlightSegment):
            option = next(
                item for item in segment.cabin_options
                if item.option_id == segment.selected_cabin_option_id
            )
            selected_options.append(f"{segment.flight_number} {option.cabin_type}")
    option_text = "、".join(selected_options) or "当前已验证选项"
    total = plan.cost_breakdown.total_cost.display_text or str(
        plan.cost_breakdown.total_cost.amount_minor
    )
    if recommendation_type == RecommendationType.CHEAPEST:
        return f"{option_text}，门到门总价{total}，是当前合格方案中的确定性最低价。"
    if recommendation_type == RecommendationType.MOST_COMFORTABLE:
        return (
            f"{option_text}，舒适度{plan.comfort_score.total_score:.1f}，"
            f"门到门总价{total}。"
        )
    return f"{option_text}，门到门总价{total}，位于成本、时长、舒适度与风险的非支配候选集。"


def _risk_rank(value: RiskLevel | str) -> int:
    normalized = value.value if isinstance(value, RiskLevel) else str(value)
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "BLOCKED": 3}.get(
        normalized,
        4,
    )


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
    gate_enabled = _deterministic_gate_enabled()
    if gate_enabled:
        llm_input = _pareto_scoped_input(llm_input)
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
        repaired, _ = _gate_if_enabled(repaired, llm_input, gate_enabled)
        repaired_invalid = validate_llm_output(
            repaired,
            llm_input,
            enforce_deterministic_semantics=gate_enabled,
        )
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
    output, gate_changed = _gate_if_enabled(output, llm_input, gate_enabled)
    invalid = validate_llm_output(
        output,
        llm_input,
        enforce_deterministic_semantics=gate_enabled,
    )
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
            final_strategy="FALLBACK_RULES" if gate_changed else "USE_ORIGINAL",
            latency_ms=latency_ms,
        )
        return _result(output, invalid_reasons=[], repair_attempted=False, repair_success=None, final_strategy="FALLBACK_RULES" if gate_changed else "USE_ORIGINAL", llm_call_id=llm_call_id, prompt_version=RECOMMENDATION_PROMPT_VERSION, model_name=getattr(provider, "model_name", None), latency_ms=latency_ms)

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
    repaired, _ = _gate_if_enabled(repaired, llm_input, gate_enabled)
    repaired_invalid = validate_llm_output(
        repaired,
        llm_input,
        enforce_deterministic_semantics=gate_enabled,
    )
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


def _deterministic_gate_enabled() -> bool:
    return os.getenv(
        "TRAVEL_DETERMINISTIC_RECOMMENDATION_GATE_ENABLED",
        "true",
    ).strip().lower() not in {"0", "false", "no", "off"}


def _pareto_scoped_input(llm_input: LLMRecommendationInput) -> LLMRecommendationInput:
    pareto = pareto_candidate_plans(eligible_plans(llm_input.candidate_plans))
    if not pareto:
        return llm_input
    return llm_input.model_copy(
        update={
            "candidate_plan_ids": [plan.plan_id for plan in pareto],
            "candidate_plans": pareto,
        },
        deep=True,
    )


def _gate_if_enabled(
    output: LLMRecommendationOutput,
    llm_input: LLMRecommendationInput,
    enabled: bool,
) -> tuple[LLMRecommendationOutput, bool]:
    if not enabled:
        return output, False
    return _apply_deterministic_gate(output, llm_input)
