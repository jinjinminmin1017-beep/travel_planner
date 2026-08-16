from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.context import RequestContext
from app.services.intent_parser import IntentParserError, parse_travel_request_with_validation
from app.services.relative_datetime_parser import RelativeDateTimeParseError, resolve_temporal_intent

SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTEXT = RequestContext("req_relative", "trace_relative", "corr_relative", "idem_relative")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026年8月20日从上海到杭州", "2026-08-20"),
        ("2026-08-20从上海到杭州", "2026-08-20"),
        ("8月20日从上海到杭州", "2026-08-20"),
        ("今天从上海到杭州", "2026-08-14"),
        ("明天从上海到杭州", "2026-08-15"),
        ("后天从上海到杭州", "2026-08-16"),
        ("下周一从上海到杭州", "2026-08-17"),
        ("下星期六从上海到杭州", "2026-08-22"),
        ("下星期天从上海到杭州", "2026-08-23"),
        ("本周六从上海到杭州", "2026-08-15"),
        ("这周六从上海到杭州", "2026-08-15"),
        ("最近的周六从上海到杭州", "2026-08-15"),
    ],
)
def test_resolves_supported_date_expressions(raw: str, expected: str) -> None:
    current = datetime(2026, 8, 14, 10, 0, tzinfo=SHANGHAI)
    resolution = resolve_temporal_intent(raw, current)
    assert resolution is not None
    assert resolution.travel_date.isoformat() == expected


def test_month_day_rolls_into_next_year_after_the_date_has_passed() -> None:
    resolution = resolve_temporal_intent("8月20日从上海到杭州", datetime(2026, 8, 21, 10, 0, tzinfo=SHANGHAI))
    assert resolution is not None
    assert resolution.travel_date.isoformat() == "2027-08-20"


@pytest.mark.parametrize(
    ("weekday", "expected"),
    [
        ("一", "2026-08-17"),
        ("二", "2026-08-18"),
        ("三", "2026-08-19"),
        ("四", "2026-08-20"),
        ("五", "2026-08-21"),
        ("六", "2026-08-22"),
        ("日", "2026-08-23"),
        ("天", "2026-08-23"),
    ],
)
def test_weekday_aliases_cover_monday_through_sunday(weekday: str, expected: str) -> None:
    current = datetime(2026, 8, 14, 10, 0, tzinfo=SHANGHAI)
    for prefix in ("下周", "下星期"):
        resolution = resolve_temporal_intent(f"{prefix}{weekday}从上海到杭州", current)
        assert resolution is not None
        assert resolution.travel_date.isoformat() == expected


@pytest.mark.parametrize(
    ("current", "raw", "expected"),
    [
        (datetime(2026, 1, 31, 10, 0, tzinfo=SHANGHAI), "明天从上海到杭州", "2026-02-01"),
        (datetime(2026, 12, 31, 10, 0, tzinfo=SHANGHAI), "后天从上海到杭州", "2027-01-02"),
        (datetime(2026, 8, 17, 10, 0, tzinfo=SHANGHAI), "最近的周一从上海到杭州", "2026-08-17"),
    ],
)
def test_relative_dates_are_stable_at_calendar_boundaries(current: datetime, raw: str, expected: str) -> None:
    resolution = resolve_temporal_intent(raw, current)
    assert resolution is not None
    assert resolution.travel_date.isoformat() == expected


@pytest.mark.parametrize("marker", ["现在出发", "马上出发", "立即出发", "即刻出发", "尽快出发"])
def test_immediate_departure_uses_one_authoritative_instant(marker: str) -> None:
    current = datetime(2026, 8, 16, 16, 57, 38, tzinfo=SHANGHAI)
    resolution = resolve_temporal_intent(f"我{marker}，从上海到杭州", current)
    assert resolution is not None
    assert resolution.travel_date.isoformat() == "2026-08-16"
    assert resolution.time_anchor_type == "DEPARTURE"
    assert resolution.earliest_departure_time == current
    assert resolution.time_window_start == current
    assert resolution.time_window_end is None


def test_immediate_departure_allows_origin_between_marker_and_departure() -> None:
    current = datetime(2026, 8, 16, 16, 57, 38, tzinfo=SHANGHAI)
    resolution = resolve_temporal_intent("我现在就要从上海市南翔镇某小区出发，到杭州市", current)
    assert resolution is not None
    assert resolution.earliest_departure_time == current


def test_conversational_now_does_not_override_tomorrow() -> None:
    current = datetime(2026, 8, 16, 16, 57, 38, tzinfo=SHANGHAI)
    resolution = resolve_temporal_intent("我现在想规划明天从上海到杭州", current)
    assert resolution is not None
    assert resolution.travel_date.isoformat() == "2026-08-17"
    assert resolution.time_anchor_type is None


def test_relative_hours_cross_midnight_and_preserve_timezone() -> None:
    current = datetime(2026, 8, 14, 23, 15, tzinfo=SHANGHAI)
    departure = resolve_temporal_intent("三小时后出发，从上海到杭州", current)
    arrival = resolve_temporal_intent("三小时后到达，从上海到杭州", current)
    assert departure is not None and arrival is not None
    assert departure.travel_date.isoformat() == "2026-08-15"
    assert departure.earliest_departure_time.isoformat() == "2026-08-15T02:15:00+08:00"
    assert departure.time_anchor_type == "DEPARTURE"
    assert arrival.latest_arrival_time.isoformat() == "2026-08-15T02:15:00+08:00"
    assert arrival.time_anchor_type == "ARRIVAL"


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (datetime(2026, 8, 14, 10, 0, tzinfo=SHANGHAI), "2026-08-14T13:00:00+08:00"),
        (datetime(2026, 8, 31, 23, 15, tzinfo=SHANGHAI), "2026-09-01T02:15:00+08:00"),
        (datetime(2026, 12, 31, 23, 15, tzinfo=SHANGHAI), "2027-01-01T02:15:00+08:00"),
    ],
)
def test_relative_hours_cover_same_day_month_and_year_boundaries(current: datetime, expected: str) -> None:
    resolution = resolve_temporal_intent("三小时后出发，从上海到杭州", current)
    assert resolution is not None
    assert resolution.earliest_departure_time.isoformat() == expected
    assert resolution.travel_date.isoformat() == expected[:10]


@pytest.mark.parametrize(
    ("raw", "question_fragment"),
    [
        ("这个周末从上海到杭州", "周六还是周日"),
        ("月底从上海到杭州", "具体哪一天"),
        ("周六从上海到杭州", "本周、下周"),
        ("昨天从上海到杭州", "今天或未来"),
        ("2026年2月30日从上海到杭州", "2 月 30 日"),
        ("现在出发，明天从上海到杭州", "现在出发"),
    ],
)
def test_ambiguous_invalid_and_past_dates_return_specific_questions(raw: str, question_fragment: str) -> None:
    with pytest.raises(RelativeDateTimeParseError) as caught:
        resolve_temporal_intent(raw, datetime(2026, 8, 14, 10, 0, tzinfo=SHANGHAI))
    assert question_fragment in caught.value.follow_up_question


def test_llm_parse_and_repair_receive_the_same_authoritative_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    current = datetime(2026, 8, 14, 23, 15, tzinfo=SHANGHAI)

    class RecordingProvider:
        source_id = "real_llm"
        model_name = "recording-relative-time"

        def __init__(self) -> None:
            self.seen: list[datetime] = []

        def parse_intent(self, raw_user_input, request_id, current_datetime, default_timezone):
            self.seen.append(current_datetime)
            return json.dumps({"travel_date": "下周六", "origin_text": "", "destination_text": "杭州"}, ensure_ascii=False)

        def repair_intent(self, raw_llm_output, invalid_reasons, raw_user_input, request_id, current_datetime, default_timezone):
            self.seen.append(current_datetime)
            return json.dumps(
                {
                    "request_id": request_id,
                    "raw_user_input": raw_user_input,
                    "travel_date": None,
                    "origin_text": "上海",
                    "destination_text": "杭州",
                    "preferences": ["BALANCED"],
                    "hard_constraints": {"allowed_transport_modes": [], "excluded_transport_modes": []},
                    "soft_preferences": {},
                },
                ensure_ascii=False,
            )

    provider = RecordingProvider()
    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", lambda: provider)
    result = parse_travel_request_with_validation(
        "下周六从上海到杭州",
        CONTEXT,
        current_datetime=current,
    )
    assert provider.seen == [current, current]
    assert result.travel_request.travel_date.isoformat() == "2026-08-22"
    assert result.llm_validation_result.final_strategy == "REPAIRED"


@pytest.mark.parametrize("llm_date", [None, "现在", "2026-08-16T16:57:38+08:00", "not-a-date"])
def test_deterministic_immediate_departure_overrides_invalid_llm_date(monkeypatch: pytest.MonkeyPatch, llm_date: str | None) -> None:
    current = datetime(2026, 8, 16, 16, 57, 38, tzinfo=SHANGHAI)

    class InvalidDateProvider:
        source_id = "real_llm"
        model_name = "invalid-relative-time"

        def parse_intent(self, raw_user_input, request_id, current_datetime, default_timezone):
            return json.dumps(
                {
                    "request_id": request_id,
                    "raw_user_input": raw_user_input,
                    "travel_date": llm_date,
                    "origin_text": "上海市南翔镇某小区",
                    "destination_text": "杭州市",
                    "preferences": ["BALANCED"],
                    "hard_constraints": {"allowed_transport_modes": [], "excluded_transport_modes": []},
                    "soft_preferences": {},
                },
                ensure_ascii=False,
            )

        def repair_intent(self, *args):
            raise AssertionError("deterministic normalization should make repair unnecessary")

    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", lambda: InvalidDateProvider())
    result = parse_travel_request_with_validation(
        "我现在就要从上海市南翔镇某小区出发，到杭州市",
        CONTEXT,
        current_datetime=current,
    )
    request = result.travel_request
    assert request.travel_date.isoformat() == "2026-08-16"
    assert request.time_anchor_type == "DEPARTURE"
    assert request.earliest_departure_time == request.time_window_start
    assert request.earliest_departure_time.datetime.isoformat() == "2026-08-16T16:57:38+08:00"
    assert request.time_window_end is None


def test_immediate_departure_falls_back_when_llm_and_repair_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    current = datetime(2026, 8, 16, 16, 57, 38, tzinfo=SHANGHAI)

    class FailingProvider:
        source_id = "real_llm"
        model_name = "failing-relative-time"

        def parse_intent(self, raw_user_input, request_id, current_datetime, default_timezone):
            return "not-json"

        def repair_intent(self, raw_llm_output, invalid_reasons, raw_user_input, request_id, current_datetime, default_timezone):
            raise ValueError("repair failed")

    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", lambda: FailingProvider())
    result = parse_travel_request_with_validation(
        "我现在就要从上海市南翔镇某小区出发，到杭州市",
        CONTEXT,
        current_datetime=current,
    )
    assert result.llm_validation_result.final_strategy == "FALLBACK_RULES"
    assert result.travel_request.earliest_departure_time.datetime == current


def test_missing_date_still_requires_input() -> None:
    with pytest.raises(IntentParserError) as caught:
        parse_travel_request_with_validation(
            "从上海到杭州",
            CONTEXT,
            current_datetime=datetime(2026, 8, 16, 10, 0, tzinfo=SHANGHAI),
        )
    assert caught.value.missing_fields == ["travel_date"]


def test_past_date_is_rejected_before_building_an_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called():
        raise AssertionError("LLM provider must not be called for a deterministic past date")

    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", fail_if_called)
    with pytest.raises(IntentParserError) as caught:
        parse_travel_request_with_validation(
            "昨天从上海到杭州",
            CONTEXT,
            current_datetime=datetime(2026, 8, 16, 10, 0, tzinfo=SHANGHAI),
        )
    assert "不能早于今天" in str(caught.value)
