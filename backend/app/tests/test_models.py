from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ErrorResponse,
    LLMRecommendationOutput,
    Money,
    PlanningStatus,
    RecommendationSlot,
    RecommendationSlotStatus,
    RecommendationType,
    RecalculateRequest,
    SelectedOption,
    SourceFailure,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    TimePoint,
    TravelHardConstraints,
    TravelPlanResponse,
    TravelRequest,
    TravelSoftPreferences,
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
    tp = TimePoint(datetime=datetime.fromisoformat("2026-05-21T09:00:00+08:00"), timezone="Asia/Shanghai")
    assert tp.timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError):
        TimePoint(datetime="not-a-date", timezone="Asia/Shanghai")


def test_timepoint_normalizes_naive_datetime_with_declared_timezone():
    point = TimePoint(datetime="2026-07-15T17:00:00", timezone="Asia/Shanghai")

    assert point.datetime.isoformat() == "2026-07-15T17:00:00+08:00"
    assert point.source_timezone == "Asia/Shanghai"


def test_timepoint_converts_aware_datetime_to_declared_timezone_without_changing_instant():
    point = TimePoint(
        datetime="2026-07-15T09:00:00+00:00",
        timezone="Asia/Shanghai",
        source_timezone="UTC",
    )

    assert point.datetime.isoformat() == "2026-07-15T17:00:00+08:00"
    assert point.datetime.astimezone(timezone.utc).isoformat() == "2026-07-15T09:00:00+00:00"
    assert point.source_timezone == "UTC"


def test_timepoint_rejects_invalid_iana_timezone():
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        TimePoint(datetime="2026-07-15T17:00:00", timezone="Mars/Olympus_Mons")


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
    assert payload.schema_version == "1.17"
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
        source_id="rail_12306_public_query",
        adapter_name="Official12306RailProvider",
        handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
        error_code=None,
        retry_count=0,
        source_used_id="rail_12306_public_query",
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
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
            change_type="SEAT_TYPE",
            target_segment_id="seg_1",
            selected_option=SelectedOption(
                option_type="CABIN",
                option_id="cabin_business",
                option_value="商务舱",
                source_option_version="provider_test_v1",
            ),
            recalculate_scope="PLAN_ONLY",
        )


def test_travel_plan_response_supports_running_failed_and_no_match_status_examples():
    travel_request = TravelRequest(
        request_id="req_status_examples",
        raw_user_input="我 2026 年 5 月 21 日从上海到青岛",
        origin_text="上海",
        destination_text="青岛",
        travel_date=datetime(2026, 5, 21).date(),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )
    common = dict(
        request_id="req_status_examples",
        trace_id="trace_status_examples",
        correlation_id="corr_status_examples",
        idempotency_key="idem_status_examples",
        travel_request=travel_request,
        destination_presentation=None,
        plans=[],
        recommendation_result=None,
        source_failures=[],
        blocked_plan_types=[],
        missing_plan_explanations=[],
        generated_at=now_timepoint(),
    )

    running = TravelPlanResponse(
        **common,
        planning_status=PlanningStatus.RUNNING,
        progress=35,
        missing_components=[],
        user_visible_warnings=["正在等待地图、铁路和航班数据源返回。"],
        async_job={
            "job_id": "job_running",
            "job_status": "RUNNING",
            "created_at": now_timepoint(),
            "updated_at": now_timepoint(),
            "polling_url": "/api/travel/jobs/job_running",
        },
    )
    failed = TravelPlanResponse(
        **common,
        planning_status=PlanningStatus.FAILED,
        progress=100,
        missing_components=["travel_plan"],
        user_visible_warnings=["核心事实缺失，当前无法生成可用方案。"],
        async_job=None,
    )
    no_match = TravelPlanResponse(
        **common,
        planning_status=PlanningStatus.NO_MATCH,
        progress=100,
        missing_components=[],
        user_visible_warnings=[],
        constraint_analysis={
            "result_type": "NO_SAFE_ALTERNATIVE",
            "summary": "没有安全备选。",
            "coverage": [],
            "alternatives": [],
        },
        async_job=None,
    )

    assert running.planning_status == PlanningStatus.RUNNING
    assert failed.planning_status == PlanningStatus.FAILED
    assert no_match.planning_status == PlanningStatus.NO_MATCH
