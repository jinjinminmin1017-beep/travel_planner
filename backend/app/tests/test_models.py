from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ErrorResponse,
    LLMRecommendationOutput,
    Money,
    RecommendationSlot,
    RecommendationSlotStatus,
    RecommendationType,
    RecalculateRequest,
    SelectedOption,
    SourceFailure,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    TimePoint,
    money,
    now_timepoint,
)


def test_money_rejects_float_and_unknown_field():
    good = money(12345)
    assert good.amount_minor == 12345
    assert good.display_text == "¥123.45"
    with pytest.raises(ValidationError):
        Money(amount_minor=12.4, currency="CNY", scale=2, display_text="¥0.12")
    with pytest.raises(ValidationError):
        Money(amount_minor=100, currency="CNY", scale=2, display_text="¥1.00", unexpected=True)


def test_timepoint_requires_datetime_shape():
    tp = TimePoint(datetime=datetime.fromisoformat("2026-05-21T09:00:00+08:00"))
    assert tp.timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError):
        TimePoint(datetime="not-a-date")


def test_error_response_required_fields_and_extra_forbidden():
    payload = ErrorResponse(
        request_id="req_1",
        error_code="BAD_INPUT",
        message="bad input",
        user_visible_message="Please retry.",
        retryable=False,
        details=None,
        generated_at=now_timepoint(),
    )
    assert payload.schema_version == "1.15"
    with pytest.raises(ValidationError):
        ErrorResponse(
            request_id="req_1",
            error_code="BAD_INPUT",
            message="bad input",
            user_visible_message="Please retry.",
            retryable=False,
            details=None,
            generated_at=now_timepoint(),
            extra_field=True,
        )


def test_source_failure_has_failure_id_and_trace_fields():
    failure = SourceFailure(
        failure_id="fail_1",
        request_id="req_1",
        trace_id="trace_1",
        correlation_id="corr_1",
        source_id="rail_authorized_partner",
        source_used_id="rail_authorized_partner",
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
        failure_class=SourceFailureClass.CORE_FACT,
        message="missing inventory",
        final_handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
        impacted_plan_types=["DIRECT_RAIL"],
        user_visible_message="Rail inventory is unavailable.",
        occurred_at=now_timepoint(),
    )
    assert failure.failure_id == "fail_1"


def test_llm_output_requires_three_slots_and_status_rules():
    with pytest.raises(ValidationError):
        LLMRecommendationOutput(
            selected_recommendations=[
                RecommendationSlot(
                    recommendation_type=RecommendationType.CHEAPEST,
                    status=RecommendationSlotStatus.AVAILABLE,
                    plan_id="plan_1",
                    reason="ok",
                )
            ],
            validation_blockers=[],
            explanation="too few",
        )
    with pytest.raises(ValidationError):
        RecommendationSlot(
            recommendation_type=RecommendationType.CHEAPEST,
            status=RecommendationSlotStatus.AVAILABLE,
            plan_id=None,
            reason="missing plan",
        )


def test_recalculate_request_change_type_must_match_option_type():
    with pytest.raises(ValidationError):
        RecalculateRequest(
            request_id="req_1",
            idempotency_key="idem_1",
            plan_id="plan_1",
            change_type="RAIL_SEAT",
            target_segment_id="seg_1",
            selected_option=SelectedOption(
                option_type="FLIGHT_CABIN",
                option_id="cabin_business",
                option_value="商务舱",
                source_option_version="provider_test_v1",
            ),
            recalculate_scope="PLAN_TOTAL",
        )
