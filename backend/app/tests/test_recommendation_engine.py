from app.core.context import RequestContext
from app.models.schemas import (
    LLMRecommendationInput,
    LLMRecommendationOutput,
    PlanLifecycleStatus,
    RecommendationEligibility,
    RecommendationSlot,
    RecommendationSlotStatus,
    RecommendationType,
)
from app.services.candidate_generator import generate_candidate_plan_pool
from app.services.intent_parser import parse_travel_request
from app.services.planner import build_plans
from app.services.recommendation import recommend_with_validation, validate_llm_output

_BASE_LLM_INPUT_JSON: str | None = None


def _llm_input():
    global _BASE_LLM_INPUT_JSON
    if _BASE_LLM_INPUT_JSON:
        return LLMRecommendationInput.model_validate_json(_BASE_LLM_INPUT_JSON)
    ctx = RequestContext("req_rec", "trace_rec", "corr_rec", "idem_rec")
    request = parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。",
        ctx,
    )
    request.earliest_departure_time = None
    request.hard_constraints.earliest_departure_time = None
    plans, *_ = build_plans(request)
    candidates = generate_candidate_plan_pool(plans, request).llm_candidate_plans
    llm_input = LLMRecommendationInput(
        request_id=request.request_id,
        travel_request=request,
        candidate_plan_ids=[plan.plan_id for plan in candidates],
        candidate_plans=candidates,
    )
    _BASE_LLM_INPUT_JSON = llm_input.model_dump_json()
    return LLMRecommendationInput.model_validate_json(_BASE_LLM_INPUT_JSON)


def _output(plan_ids: list[str]) -> LLMRecommendationOutput:
    return LLMRecommendationOutput(
        selected_recommendations=[
            RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[0], reason="cheapest"),
            RecommendationSlot(recommendation_type=RecommendationType.MOST_COMFORTABLE, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[1], reason="comfortable"),
            RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[2], reason="balanced"),
        ],
        validation_blockers=[],
        explanation="ok",
    )


def test_validate_llm_output_rejects_candidate_pool_violations():
    llm_input = _llm_input()
    invalid = _output(["outside_plan", llm_input.candidate_plan_ids[1], llm_input.candidate_plan_ids[2]])

    reasons = validate_llm_output(invalid, llm_input)

    assert any("not in candidate_plan_ids" in reason for reason in reasons)


def test_validate_llm_output_rejects_non_eligible_plan():
    llm_input = _llm_input()
    llm_input.candidate_plans[0].recommendation_eligibility = RecommendationEligibility.NOT_RECOMMENDED
    invalid = _output(llm_input.candidate_plan_ids[:3])

    reasons = validate_llm_output(invalid, llm_input)

    assert any("not ELIGIBLE" in reason for reason in reasons)


def test_validate_llm_output_rejects_duplicate_recommendation_types():
    llm_input = _llm_input()
    output = LLMRecommendationOutput(
        selected_recommendations=[
            RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=llm_input.candidate_plan_ids[0], reason="one"),
            RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=llm_input.candidate_plan_ids[1], reason="duplicate"),
            RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=llm_input.candidate_plan_ids[2], reason="three"),
        ],
        validation_blockers=[],
        explanation="invalid",
    )

    reasons = validate_llm_output(output, llm_input)

    assert "recommendation slots must be CHEAPEST, MOST_COMFORTABLE, BALANCED" in reasons


def test_validate_llm_output_rejects_unselectable_and_expired_plan():
    llm_input = _llm_input()
    llm_input.candidate_plans[0].can_be_selected_by_llm = False
    llm_input.candidate_plans[1].plan_lifecycle_status = PlanLifecycleStatus.EXPIRED
    invalid = _output(llm_input.candidate_plan_ids[:3])

    reasons = validate_llm_output(invalid, llm_input)

    assert any("cannot be selected" in reason for reason in reasons)
    assert any("not active" in reason for reason in reasons)


def test_recommendation_repair_once_success(monkeypatch):
    llm_input = _llm_input()

    class _RepairingProvider:
        source_id = "real_llm"
        model_name = "test-recommend-model"

        def recommend(self, _llm_input):
            return _output(["outside_plan", llm_input.candidate_plan_ids[1], llm_input.candidate_plan_ids[2]])

        def repair_recommendation(self, _llm_input, invalid_reasons):
            assert invalid_reasons
            return _output(llm_input.candidate_plan_ids[:3])

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _RepairingProvider())

    result = recommend_with_validation(llm_input)

    assert result is not None
    assert result.llm_validation_result.repair_attempted is True
    assert result.llm_validation_result.repair_success is True
    assert result.llm_validation_result.final_strategy == "REPAIRED"
    assert result.llm_validation_result.prompt_version == "repair_prompt_v1.0"
    assert result.llm_validation_result.model_name == "test-recommend-model"


def test_recommendation_repairs_schema_validation_failure(monkeypatch):
    llm_input = _llm_input()

    class _SchemaBrokenProvider:
        source_id = "real_llm"
        model_name = "test-recommend-model"

        def recommend(self, _llm_input):
            raise ValueError("selected_recommendations field required; recommendations extra input")

        def repair_recommendation(self, _llm_input, invalid_reasons):
            assert any("schema validation failed" in reason for reason in invalid_reasons)
            return _output(llm_input.candidate_plan_ids[:3])

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _SchemaBrokenProvider())

    result = recommend_with_validation(llm_input)

    assert result is not None
    assert result.llm_validation_result.repair_attempted is True
    assert result.llm_validation_result.repair_success is True
    assert result.llm_validation_result.final_strategy == "REPAIRED"
    assert any("schema validation failed" in reason for reason in result.llm_validation_result.invalid_reasons)


def test_recommendation_repair_failure_returns_none(monkeypatch):
    llm_input = _llm_input()

    class _BrokenProvider:
        source_id = "real_llm"
        model_name = "test-recommend-model"

        def recommend(self, _llm_input):
            return _output(["outside_plan", llm_input.candidate_plan_ids[1], llm_input.candidate_plan_ids[2]])

        def repair_recommendation(self, _llm_input, invalid_reasons):
            return _output(["still_outside", llm_input.candidate_plan_ids[1], llm_input.candidate_plan_ids[2]])

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _BrokenProvider())

    assert recommend_with_validation(llm_input) is None
