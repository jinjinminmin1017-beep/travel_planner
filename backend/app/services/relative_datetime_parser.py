from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"
SHANGHAI_TIMEZONE = ZoneInfo(DEFAULT_TIMEZONE)


class RelativeDateTimeParseError(ValueError):
    def __init__(self, message: str, follow_up_question: str) -> None:
        super().__init__(message)
        self.follow_up_question = follow_up_question


@dataclass(frozen=True)
class ResolvedTemporalIntent:
    travel_date: date
    time_anchor_type: Literal["DEPARTURE", "ARRIVAL"] | None = None
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    earliest_departure_time: datetime | None = None
    latest_arrival_time: datetime | None = None


_WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_IMMEDIATE_PATTERNS = (
    re.compile(r"现在\s*就要\s*(?:从[^，,。；;]{1,100})?\s*出发"),
    re.compile(r"现在\s*(?:从[^，,。；;]{1,100})?\s*出发"),
    re.compile(r"(?:马上|立即|即刻|尽快)\s*(?:从[^，,。；;]{1,100})?\s*出发"),
)

_QUALIFIED_WEEKDAY_PATTERN = re.compile(
    r"(?P<prefix>本周|这周|本星期|这星期|下周|下星期|最近的周|最近的星期)\s*"
    r"(?P<weekday>[一二三四五六日天])"
)


def normalize_current_datetime(value: datetime | None = None) -> datetime:
    current = value or datetime.now(SHANGHAI_TIMEZONE)
    if current.tzinfo is None or current.utcoffset() is None:
        return current.replace(tzinfo=SHANGHAI_TIMEZONE)
    return current.astimezone(SHANGHAI_TIMEZONE)


def resolve_temporal_intent(raw: str, current_datetime: datetime) -> ResolvedTemporalIntent | None:
    current = normalize_current_datetime(current_datetime)
    text = raw.strip()

    if "这个周末" in text or "本周末" in text:
        raise RelativeDateTimeParseError("出行日期需要明确到具体一天。", "这个周末你想周六还是周日出发？")
    if "月底" in text or "月末" in text:
        raise RelativeDateTimeParseError("月底无法唯一对应一个出行日期。", "请告诉我月底具体哪一天出发？")

    immediate = _contains_immediate_departure(text)
    if immediate:
        if _contains_conflicting_explicit_time(text):
            raise RelativeDateTimeParseError(
                "立即出发与另一个明确日期或时间同时出现，无法确定以哪个为准。",
                "你想现在出发，还是按后面写的日期或时间出发？",
            )
        return ResolvedTemporalIntent(
            travel_date=current.date(),
            time_anchor_type="DEPARTURE",
            time_window_start=current,
            earliest_departure_time=current,
        )

    relative_hours = re.search(r"([零〇一二两三四五六七八九十百\d]+)\s*(?:个)?小时后", text)
    if relative_hours:
        hours = _parse_positive_number(relative_hours.group(1))
        if hours is None:
            raise RelativeDateTimeParseError("无法识别相对小时数。", "请用明确数字说明几小时后出发或到达。")
        target = current + timedelta(hours=hours)
        suffix = text[relative_hours.end() : relative_hours.end() + 8]
        if re.search(r"(?:到达|抵达|到站|落地)", suffix):
            return ResolvedTemporalIntent(
                travel_date=target.date(),
                time_anchor_type="ARRIVAL",
                time_window_end=target,
                latest_arrival_time=target,
            )
        return ResolvedTemporalIntent(
            travel_date=target.date(),
            time_anchor_type="DEPARTURE",
            time_window_start=target,
            earliest_departure_time=target,
        )

    resolved_date = _resolve_date(text, current.date())
    if resolved_date is None:
        if re.search(r"(?:周|星期)\s*[一二三四五六日天]", text):
            raise RelativeDateTimeParseError(
                "星期表达缺少本周、下周或最近的限定。",
                "你说的星期几是本周、下周，还是最近的一次？",
            )
        return None

    if resolved_date < current.date():
        raise RelativeDateTimeParseError(
            "出行日期不能早于今天。",
            "请选择今天或未来的具体出行日期。",
        )
    return ResolvedTemporalIntent(travel_date=resolved_date)


def _contains_immediate_departure(raw: str) -> bool:
    return any(pattern.search(raw) for pattern in _IMMEDIATE_PATTERNS)


def _contains_conflicting_explicit_time(raw: str) -> bool:
    without_immediate = raw
    for pattern in _IMMEDIATE_PATTERNS:
        without_immediate = pattern.sub("", without_immediate)
    return bool(
        re.search(
            r"昨天|今天|明天|后天|[零〇一二两三四五六七八九十百\d]+\s*(?:个)?小时后|"
            r"(?:20\d{2}\s*年\s*)?\d{1,2}\s*(?:月|[./-])\s*\d{1,2}\s*[日号]?|"
            r"(?:本周|这周|本星期|这星期|下周|下星期|最近的周|最近的星期)\s*[一二三四五六日天]|"
            r"(?:上午|下午|晚上|中午|凌晨)?\s*\d{1,2}\s*(?:点|[:：])",
            without_immediate,
        )
    )


def _resolve_date(raw: str, today: date) -> date | None:
    if "昨天" in raw:
        return today - timedelta(days=1)
    if "后天" in raw:
        return today + timedelta(days=2)
    if "明天" in raw:
        return today + timedelta(days=1)
    if "今天" in raw:
        return today

    relative_days = re.search(r"([零〇一二两三四五六七八九十百\d]+)\s*天后", raw)
    if relative_days:
        days = _parse_positive_number(relative_days.group(1))
        if days is not None:
            return today + timedelta(days=days)

    weekday = _QUALIFIED_WEEKDAY_PATTERN.search(raw)
    if weekday:
        target_weekday = _WEEKDAY_INDEX[weekday.group("weekday")]
        prefix = weekday.group("prefix")
        monday = today - timedelta(days=today.weekday())
        if prefix in {"下周", "下星期"}:
            return monday + timedelta(days=7 + target_weekday)
        if prefix in {"最近的周", "最近的星期"}:
            return today + timedelta(days=(target_weekday - today.weekday()) % 7)
        return monday + timedelta(days=target_weekday)

    year_month_day = re.search(
        r"(20\d{2})\s*(?:年\s*|[-./])\s*(\d{1,2})\s*(?:月|[-./])\s*(\d{1,2})\s*[日号]?",
        raw,
    )
    if year_month_day:
        return _checked_date(*map(int, year_month_day.groups()))

    iso_date = re.search(r"(?<!\d)(20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", raw)
    if iso_date:
        return _checked_date(*map(int, iso_date.groups()))

    month_day = re.search(r"(?<!\d)(\d{1,2})\s*(?:月|[./])\s*(\d{1,2})\s*[日号]?", raw)
    if month_day:
        month, day = map(int, month_day.groups())
        parsed = _checked_date(today.year, month, day)
        return _checked_date(today.year + 1, month, day) if parsed < today else parsed
    return None


def _checked_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise RelativeDateTimeParseError(
            "出行日期不是有效的日历日期。",
            "请检查年月日，例如不要使用 2 月 30 日。",
        ) from exc


def _parse_positive_number(value: str) -> int | None:
    if value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    if value == "十":
        return 10
    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = _CHINESE_DIGITS.get(left, 1 if not left else -1)
        remainder = _parse_chinese_under_100(right) if right else 0
        parsed = hundreds * 100 + remainder
        return parsed if parsed > 0 else None
    parsed = _parse_chinese_under_100(value)
    return parsed if parsed and parsed > 0 else None


def _parse_chinese_under_100(value: str) -> int | None:
    if not value:
        return 0
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CHINESE_DIGITS.get(left, 1 if not left else -1)
        ones = _CHINESE_DIGITS.get(right, 0 if not right else -1)
        if tens < 0 or ones < 0:
            return None
        return tens * 10 + ones
    if len(value) == 1:
        return _CHINESE_DIGITS.get(value)
    return None
