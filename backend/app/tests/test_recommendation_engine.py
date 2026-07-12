import json
from datetime import date

from app.core.context import RequestContext
from app.data_sources.llm_providers import OpenAICompatibleLLMProvider, _prompt, _recommendation_selection_payload, _recommendation_user_prompt
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


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class _RecordingLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        content = self.responses.pop(0)
        return _FakeLLMResponse(content)


def _llm_input():
    global _BASE_LLM_INPUT_JSON
    if _BASE_LLM_INPUT_JSON:
        return LLMRecommendationInput.model_validate_json(_BASE_LLM_INPUT_JSON)
    ctx = RequestContext("req_rec", "trace_rec", "corr_rec", "idem_rec")
    request = parse_travel_request(
        "2026-05-21 from Beijing to Guangzhou, comfortable and cheapest, train or flight",
        ctx,
    )
    request.earliest_departure_time = None
    request.hard_constraints.earliest_departure_time = None
    request.time_window_start = None
    request.time_window_end = None
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


def test_intent_prompt_uses_minimal_contract_and_dynamic_user_context():
    system_prompt = _prompt("intent_parser_prompt_v1_0.txt")
    client = _RecordingLLMClient(['{"schema_version":"1.17"}'])
    provider = OpenAICompatibleLLMProvider(api_key="test-key", model="test-model", client=client)

    provider.parse_intent("2026-07-09 from Beijing to Shanghai in the morning", "req_prompt", date(2026, 7, 7), "Asia/Shanghai")

    request_payload = client.requests[0]["json"]
    user_prompt = request_payload["messages"][1]["content"]
    assert request_payload["response_format"] == {"type": "json_object"}
    assert "full TravelRequest Schema" not in system_prompt
    assert "Required minimum fields" in system_prompt
    assert "time_window_start" in system_prompt
    assert "TimePoint object has exactly these fields: datetime, timezone, source_timezone" in system_prompt
    assert "request_id: req_prompt" in user_prompt
    assert "default_timezone: Asia/Shanghai" in user_prompt
    assert "current_date: 2026-07-07" in user_prompt
    assert "2026-07-09 from Beijing to Shanghai in the morning" in user_prompt


def test_recommendation_prompt_lists_exact_plan_ids_without_copyable_plan_id_placeholder():
    llm_input = _llm_input()
    system_prompt = _prompt("recommendation_prompt_v1_0.txt")

    prompt = _recommendation_user_prompt(llm_input)

    assert "Legal plan_id list" in prompt
    for plan_id in llm_input.candidate_plan_ids:
        assert f"- {plan_id}" in prompt
    assert "copy-from-user-prompt" not in system_prompt
    assert '"plan_id":"must come from legal candidate_plan_ids"' not in prompt
    assert '"plan_id": "must come from input.candidate_plan_ids"' not in prompt


def test_recommendation_prompt_uses_compact_selection_payload():
    llm_input = _llm_input()

    payload = _recommendation_selection_payload(llm_input)
    prompt = _recommendation_user_prompt(llm_input)

    assert len(prompt) < len(llm_input.model_dump_json())
    assert "transfer_options" not in prompt
    assert "booking_redirects" not in prompt
    assert payload["candidate_plan_ids"] == llm_input.candidate_plan_ids
    assert {plan["plan_id"] for plan in payload["candidate_plans"]} == set(llm_input.candidate_plan_ids)


def test_recommendation_repair_prompt_repeats_legal_plan_ids_and_original_output():
    llm_input = _llm_input()
    raw_invalid_output = '{"schema_version":"1.17","recommendations":[]}'
    repaired_output = _output(llm_input.candidate_plan_ids[:3]).model_dump(mode="json")
    client = _RecordingLLMClient([json.dumps(repaired_output)])
    provider = OpenAICompatibleLLMProvider(api_key="test-key", model="test-model", client=client)
    provider._last_recommendation_raw_output = raw_invalid_output

    provider.repair_recommendation(llm_input, ["schema validation failed: recommendations extra input"])

    user_prompt = client.requests[0]["json"]["messages"][1]["content"]
    assert "target_schema: LLMRecommendationOutput Schema V1.17" in user_prompt
    assert "schema validation failed: recommendations extra input" in user_prompt
    assert "previous_raw_llm_output:" in user_prompt
    assert raw_invalid_output in user_prompt
    assert "Legal plan_id list" in user_prompt
    for plan_id in llm_input.candidate_plan_ids:
        assert f"- {plan_id}" in user_prompt


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
