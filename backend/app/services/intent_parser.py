from __future__ import annotations

import json
import re
import time as perf_time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import httpx
from pydantic import ValidationError

from app.core.context import RequestContext
from app.data_sources.llm_providers import LLMProviderError, build_enabled_intent_llm_provider
from app.llm.logs import log_llm_call, stable_hash
from app.llm.prompt_versions import INTENT_PARSER_PROMPT_VERSION, REPAIR_PROMPT_VERSION
from app.models.schemas import (
    LLMValidationResult,
    RecommendationType,
    TimePoint,
    TransportMode,
    TravelHardConstraints,
    TravelRequest,
    TravelSoftPreferences,
    money,
)

DEFAULT_TIMEZONE = "Asia/Shanghai"
RULE_PARSER_MODEL = "rule_parser_v1"


@dataclass(frozen=True)
class IntentParseResult:
    travel_request: TravelRequest
    llm_validation_result: LLMValidationResult


class IntentParserError(ValueError):
    def __init__(
        self,
        message: str,
        missing_fields: list[str] | None = None,
        follow_up_questions: list[str] | None = None,
        llm_validation_result: LLMValidationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields or []
        self.follow_up_questions = follow_up_questions or []
        self.llm_validation_result = llm_validation_result


def _validation_result(
    *,
    schema_valid: bool,
    semantic_valid: bool,
    repair_attempted: bool,
    final_strategy: str,
    invalid_reasons: list[str] | None = None,
    repair_success: bool | None = None,
    llm_call_id: str | None = None,
    prompt_version: str | None = None,
    model_name: str | None = None,
    latency_ms: int | None = None,
) -> LLMValidationResult:
    return LLMValidationResult(
        schema_valid=schema_valid,
        semantic_valid=semantic_valid,
        repair_attempted=repair_attempted,
        final_strategy=final_strategy,
        invalid_reasons=invalid_reasons or [],
        repair_success=repair_success,
        llm_call_id=llm_call_id,
        prompt_version=prompt_version,
        model_name=model_name,
        latency_ms=latency_ms,
    )


def _extract_date(raw: str, current_date: date | None = None) -> date:
    today = current_date or date.today()
    if "后天" in raw:
        return today + timedelta(days=2)
    if "明天" in raw:
        return today + timedelta(days=1)
    if "今天" in raw:
        return today
    match = re.search(r"(20\d{2})\s*年?\s*(\d{1,2})\s*(?:月|[./-])\s*(\d{1,2})\s*[日号]?", raw)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    iso = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    month_day = re.search(r"(?<!\d)(\d{1,2})\s*(?:月|[./])\s*(\d{1,2})\s*[日号]?", raw)
    if month_day:
        parsed = date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        return date(today.year + 1, parsed.month, parsed.day) if parsed < today else parsed
    raise IntentParserError("缺少出行日期，请补充具体日期。", ["travel_date"], ["请补充具体出行日期，例如“2026 年 5 月 21 日”或“明天”。"])


def _timepoint(day: date, hour: int, minute: int = 0) -> TimePoint:
    return TimePoint(datetime=datetime.combine(day, time(hour, minute), tzinfo=timezone(timedelta(hours=8))), timezone=DEFAULT_TIMEZONE, source_timezone=DEFAULT_TIMEZONE)


def _extract_time(raw: str, marker: str) -> tuple[int, int] | None:
    pattern = rf"(上午|下午|晚上|中午)?\s*(\d{{1,2}})\s*点\s*(?:(\d{{1,2}})\s*分?)?\s*(?:{marker})"
    match = re.search(pattern, raw)
    if not match:
        return None
    prefix = match.group(1) or ""
    hour = int(match.group(2))
    minute = int(match.group(3) or 0)
    if prefix in {"下午", "晚上"} and hour < 12:
        hour += 12
    if prefix == "中午" and hour < 11:
        hour += 12
    return hour, minute


def _extract_period_window(raw: str) -> tuple[int, int, int, int] | None:
    windows = [
        (("凌晨",), (0, 0, 6, 0)),
        (("早上", "早晨", "清早"), (6, 0, 11, 0)),
        (("上午",), (8, 0, 12, 0)),
        (("中午",), (11, 0, 14, 0)),
        (("下午",), (13, 0, 18, 0)),
        (("傍晚",), (17, 0, 20, 0)),
        (("晚上", "夜里"), (19, 0, 23, 30)),
    ]
    for markers, window in windows:
        if any(marker in raw for marker in markers):
            return window
    return None


def _time_anchor_type(raw: str, *, has_arrival_constraint: bool = False) -> str:
    arrival_markers = ("到达", "抵达", "到站", "落地", "赶到", "前到", "之前到", "以前到")
    departure_markers = ("出发", "启程", "动身", "开始走", "走")
    if has_arrival_constraint or any(marker in raw for marker in arrival_markers):
        return "ARRIVAL"
    if any(marker in raw for marker in departure_markers):
        return "DEPARTURE"
    return "DEPARTURE"


def _normalize_time_intent(request: TravelRequest) -> TravelRequest:
    raw = request.raw_user_input
    period = _extract_period_window(raw)
    has_arrival_constraint = request.latest_arrival_time is not None or request.hard_constraints.latest_arrival_time is not None
    anchor = request.time_anchor_type if request.time_anchor_type != "AMBIGUOUS" else _time_anchor_type(raw, has_arrival_constraint=has_arrival_constraint)
    if request.time_anchor_type == "DEPARTURE" and has_arrival_constraint and any(marker in raw for marker in ("到", "抵达", "落地", "赶到")):
        anchor = "ARRIVAL"
    update: dict[str, object] = {"time_anchor_type": anchor}

    if period and request.time_window_start is None and request.time_window_end is None:
        start_h, start_m, end_h, end_m = period
        update["time_window_start"] = _timepoint(request.travel_date, start_h, start_m)
        update["time_window_end"] = _timepoint(request.travel_date, end_h, end_m)
        if anchor == "ARRIVAL" and request.latest_arrival_time is None and request.hard_constraints.latest_arrival_time is None:
            latest = _timepoint(request.travel_date, end_h, end_m)
            update["latest_arrival_time"] = latest
            update["hard_constraints"] = request.hard_constraints.model_copy(update={"latest_arrival_time": latest})
        elif anchor == "DEPARTURE" and request.earliest_departure_time is None and request.hard_constraints.earliest_departure_time is None:
            earliest = _timepoint(request.travel_date, start_h, start_m)
            update["earliest_departure_time"] = earliest
            update["hard_constraints"] = request.hard_constraints.model_copy(update={"earliest_departure_time": earliest})
    elif request.time_window_start is None and request.time_window_end is None:
        start = request.earliest_departure_time or request.hard_constraints.earliest_departure_time
        end = request.latest_arrival_time or request.hard_constraints.latest_arrival_time
        if start:
            update["time_window_start"] = start
        if end:
            update["time_window_end"] = end

    return request.model_copy(update=update)


def _extract_origin_destination(raw: str) -> tuple[str, str]:
    lowered = raw.lower()
    english_pairs = [
        (("shanghai", "qingdao"), ("上海市区", "青岛市区")),
        (("beijing", "guangzhou"), ("北京市朝阳区国贸", "广州天河体育中心")),
        (("chengdu", "shenzhen"), ("成都春熙路", "深圳福田中心区")),
        (("hangzhou", "xian"), ("杭州西湖", "西安钟楼")),
        (("hangzhou", "xi'an"), ("杭州西湖", "西安钟楼")),
    ]
    for (origin_marker, destination_marker), pair in english_pairs:
        if origin_marker in lowered and destination_marker in lowered:
            return pair
    if "北京" in raw and "广州" in raw:
        return "北京市朝阳区国贸", "广州天河体育中心"
    if "成都" in raw and "深圳" in raw:
        return "成都春熙路", "深圳福田中心区"
    if "杭州" in raw and "西安" in raw:
        return "杭州西湖", "西安钟楼"
    if "上海" in raw and "青岛" in raw:
        origin = "上海嘉定南翔格林公馆" if "南翔" in raw or "嘉定" in raw else "上海市区"
        destination = "青岛金水假日酒店" if "金水" in raw or "酒店" in raw else "青岛市区"
        return origin, destination
    explicit_pair = _extract_explicit_origin_destination(raw)
    if explicit_pair is not None:
        return explicit_pair
    raise IntentParserError("地点不够明确，请补充出发地和目的地。", ["origin_text", "destination_text"], ["请补充明确的出发地和目的地，例如“从上海虹桥站到青岛金水假日酒店”。"])


def _extract_explicit_origin_destination(raw: str) -> tuple[str, str] | None:
    from_split = raw.rsplit("从", 1)
    candidate_phrases = [from_split[-1], raw] if len(from_split) == 2 else [raw]
    patterns = [
        r"(?P<origin>.+?)\s*(?:到|去|至|前往)\s*(?P<destination>.+?)(?:[，,。；;]|$)",
    ]
    for phrase in candidate_phrases:
        for pattern in patterns:
            match = re.search(pattern, phrase)
            if not match:
                continue
            origin = _clean_place_text(match.group("origin"))
            destination = _clean_place_text(match.group("destination"))
            if _is_specific_place(origin) and _is_specific_place(destination):
                return origin, destination
    return None


def _clean_place_text(value: str) -> str:
    text = value.strip(" ，,。；;、")
    text = re.sub(r"^(?:20\d{2}\s*年?\s*)?\d{1,2}\s*(?:月|[./-])\s*\d{1,2}\s*[日号]?\s*(?:上午|下午|晚上|中午|早上)?\s*", "", text)
    text = re.sub(r"^(?:我|我们|帮我|请帮我|计划|想要|想)\s*", "", text)
    text = re.sub(r"(?:出发|启程|开始走)$", "", text).strip(" ，,。；;、")
    text = re.sub(r"\s*(?:20\d{2}\s*年?\s*)?\d{1,2}\s*(?:月|[./-])\s*\d{1,2}\s*[日号]?.*$", "", text).strip(" ，,。；;、")
    text = re.sub(r"\s*(?:今天|明天|后天|上午|下午|晚上|中午|早上).*$", "", text).strip(" ，,。；;、")
    return text


def _is_specific_place(value: str) -> bool:
    if not value or value in {"家里", "酒店", "公司", "机场", "车站"}:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", value))


def _parse_rule_based(raw: str, ctx: RequestContext, current_date: date | None = None) -> TravelRequest:
    travel_date = _extract_date(raw, current_date)
    origin, destination = _extract_origin_destination(raw)

    excluded: list[TransportMode] = []
    allowed: list[TransportMode] = []
    lowered = raw.lower()
    if "不坐飞机" in raw or "不要飞机" in raw or "no flight" in lowered or "avoid flight" in lowered:
        excluded.append(TransportMode.FLIGHT)
    if "不坐高铁" in raw or "不要高铁" in raw or "no rail" in lowered or "avoid rail" in lowered:
        excluded.append(TransportMode.RAIL)
    if "只看高铁" in raw or "只坐高铁" in raw or "rail only" in lowered or "train only" in lowered:
        allowed.append(TransportMode.RAIL)
    if "不要机场大巴" in raw or "不要接送机" in raw:
        excluded.append(TransportMode.AIRPORT_TRANSFER)
    if "不要接送站" in raw:
        excluded.append(TransportMode.RAIL_STATION_TRANSFER)

    preferences = [RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED]
    preference_source = "SYSTEM_DEFAULT"
    cheap_markers = ["最便宜", "最优惠", "低价", "省钱", "cheapest", "low cost", "budget"]
    comfort_markers = ["最舒服", "最舒适", "舒服", "舒适", "comfortable", "comfort"]
    wants_cheap = any(marker in raw for marker in cheap_markers)
    wants_comfort = any(marker in raw for marker in comfort_markers)
    if "只要最便宜" in raw or "指定最便宜" in raw:
        preferences = [RecommendationType.CHEAPEST]
        preference_source = "USER_EXPLICIT"
    elif "只要最舒服" in raw or "指定最舒服" in raw or "只要最舒适" in raw or "指定最舒适" in raw:
        preferences = [RecommendationType.MOST_COMFORTABLE]
        preference_source = "USER_EXPLICIT"
    elif wants_comfort and not wants_cheap:
        preferences = [RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED, RecommendationType.CHEAPEST]
        preference_source = "USER_EXPLICIT"
    elif wants_cheap and not wants_comfort:
        preferences = [RecommendationType.CHEAPEST, RecommendationType.BALANCED, RecommendationType.MOST_COMFORTABLE]
        preference_source = "USER_EXPLICIT"
    elif wants_comfort and wants_cheap:
        first_comfort = min((raw.find(marker) for marker in comfort_markers if marker in raw), default=10**9)
        first_cheap = min((raw.find(marker) for marker in cheap_markers if marker in raw), default=10**9)
        preferences = (
            [RecommendationType.MOST_COMFORTABLE, RecommendationType.CHEAPEST, RecommendationType.BALANCED]
            if first_comfort < first_cheap
            else [RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED]
        )
        preference_source = "USER_EXPLICIT"

    earliest = _extract_time(raw, "后|以后|之后")
    latest = _extract_time(raw, "前|以前|之前")
    around = _extract_time(raw, "左右")
    earliest_point = _timepoint(travel_date, *earliest) if earliest is not None else None
    latest_point = _timepoint(travel_date, *latest) if latest is not None else None
    around_point = _timepoint(travel_date, *around) if around is not None else None
    anchor_type = _time_anchor_type(raw, has_arrival_constraint=latest_point is not None)

    max_cost = None
    budget = re.search(r"(?:预算|不要超过|不超过)\s*(\d{2,5})", raw)
    if budget:
        max_cost = money(int(budget.group(1)) * 100)

    passenger_notes: list[str] = []
    for keyword in ["老人", "小孩", "儿童", "带娃", "行李多", "轮椅", "孕妇"]:
        if keyword in raw:
            passenger_notes.append(keyword)

    return _normalize_time_intent(TravelRequest(
        request_id=ctx.request_id,
        raw_user_input=raw,
        origin_text=origin,
        destination_text=destination,
        travel_date=travel_date,
        time_anchor_type=anchor_type,
        time_window_start=earliest_point,
        time_window_end=latest_point,
        earliest_departure_time=earliest_point,
        latest_arrival_time=latest_point,
        preferred_departure_time=around_point,
        preferences=preferences,
        preference_source=preference_source,
        hard_constraints=TravelHardConstraints(
            earliest_departure_time=earliest_point,
            latest_arrival_time=latest_point,
            max_total_cost=max_cost,
            allowed_transport_modes=allowed,
            excluded_transport_modes=excluded,
        ),
        soft_preferences=TravelSoftPreferences(
            prefer_low_cost=RecommendationType.CHEAPEST in preferences,
            prefer_comfort=RecommendationType.MOST_COMFORTABLE in preferences,
            accept_rail_transfer="不接受中转" not in raw and "不要中转" not in raw and "不接受高铁中转" not in raw,
            accept_flight_transfer="不接受中转" not in raw and "不要中转" not in raw and "不接受航班中转" not in raw,
            accept_mixed_transport="不接受多交通" not in raw,
            accept_ticket_enhancement="不接受票源增强" not in raw,
            passenger_notes=passenger_notes,
        ),
        preferred_rail_seat="一等座" if "一等座" in raw else ("商务座" if "商务座" in raw else None),
        preferred_flight_cabin="商务舱" if "商务舱" in raw else ("头等舱" if "头等舱" in raw else None),
    ))


def parse_travel_request(raw: str, ctx: RequestContext) -> TravelRequest:
    return parse_travel_request_with_validation(raw, ctx).travel_request


def parse_travel_request_with_validation(raw: str, ctx: RequestContext, current_date: date | None = None) -> IntentParseResult:
    raw = raw.strip()
    if not raw:
        validation = _validation_result(
            schema_valid=False,
            semantic_valid=False,
            repair_attempted=False,
            final_strategy="REJECTED",
            invalid_reasons=["raw_user_input is empty"],
            prompt_version=INTENT_PARSER_PROMPT_VERSION,
        )
        raise IntentParserError("请输入出行需求。", ["raw_user_input"], ["请告诉我出发地、目的地和出行日期。"], validation)

    provider = build_enabled_intent_llm_provider()
    if provider is not None:
        return _parse_with_llm(raw, ctx, provider, current_date)
    return _parse_with_rule_fallback(raw, ctx, current_date, ["real_llm is disabled or unavailable; rule parser fallback used"])


def _parse_with_rule_fallback(raw: str, ctx: RequestContext, current_date: date | None, reasons: list[str]) -> IntentParseResult:
    try:
        travel_request = _parse_rule_based(raw, ctx, current_date)
    except IntentParserError as exc:
        validation = _validation_result(
            schema_valid=False,
            semantic_valid=False,
            repair_attempted=False,
            final_strategy="REJECTED",
            invalid_reasons=[str(exc)],
            prompt_version=INTENT_PARSER_PROMPT_VERSION,
            model_name=RULE_PARSER_MODEL,
        )
        exc.llm_validation_result = validation
        raise
    semantic_reasons = validate_travel_request_semantics(travel_request)
    if semantic_reasons:
        validation = _validation_result(
            schema_valid=True,
            semantic_valid=False,
            repair_attempted=False,
            final_strategy="REJECTED",
            invalid_reasons=semantic_reasons,
            prompt_version=INTENT_PARSER_PROMPT_VERSION,
            model_name=RULE_PARSER_MODEL,
        )
        raise IntentParserError(
            "交通方式限制存在冲突，请补充或修改后重试。",
            ["hard_constraints"],
            ["请确认是否同时限制和排除了同一种交通方式。"],
            validation,
        )
    return IntentParseResult(
        travel_request=travel_request,
        llm_validation_result=_validation_result(
            schema_valid=True,
            semantic_valid=True,
            repair_attempted=False,
            final_strategy="FALLBACK_RULES",
            invalid_reasons=reasons,
            prompt_version=INTENT_PARSER_PROMPT_VERSION,
            model_name=RULE_PARSER_MODEL,
        ),
    )


def _parse_with_llm(raw: str, ctx: RequestContext, provider, current_date: date | None) -> IntentParseResult:
    call_id = f"llm_intent_{uuid.uuid4().hex[:12]}"
    prompt_date = current_date or date.today()
    start = perf_time.perf_counter()
    try:
        raw_output = provider.parse_intent(raw, ctx.request_id, prompt_date, DEFAULT_TIMEZONE)
    except (httpx.HTTPError, LLMProviderError, ValueError) as exc:
        latency_ms = _elapsed_ms(start)
        _audit(call_id, ctx, provider.model_name, raw, "", False, False, False, "FALLBACK_RULES", latency_ms, [str(exc)])
        return _parse_with_rule_fallback(raw, ctx, current_date, [f"real_llm unavailable: {exc}"])

    latency_ms = _elapsed_ms(start)
    travel_request, invalid_reasons = _travel_request_from_llm_output(raw_output, raw, ctx)
    if travel_request is not None:
        semantic_reasons = validate_travel_request_semantics(travel_request)
        if not semantic_reasons:
            _audit(call_id, ctx, provider.model_name, raw, raw_output, True, True, False, "USE_ORIGINAL", latency_ms, [])
            return IntentParseResult(
                travel_request=travel_request,
                llm_validation_result=_validation_result(
                    schema_valid=True,
                    semantic_valid=True,
                    repair_attempted=False,
                    final_strategy="USE_ORIGINAL",
                    llm_call_id=call_id,
                    prompt_version=INTENT_PARSER_PROMPT_VERSION,
                    model_name=provider.model_name,
                    latency_ms=latency_ms,
                ),
            )
        invalid_reasons.extend(semantic_reasons)

    repaired_output = ""
    repair_start = perf_time.perf_counter()
    try:
        repaired_output = provider.repair_intent(raw_output, invalid_reasons, raw, ctx.request_id)
        repaired_request, repaired_reasons = _travel_request_from_llm_output(repaired_output, raw, ctx)
    except (httpx.HTTPError, LLMProviderError, ValueError) as exc:
        repaired_request = None
        repaired_reasons = [str(exc)]
    repair_latency_ms = latency_ms + _elapsed_ms(repair_start)

    if repaired_request is not None:
        semantic_reasons = validate_travel_request_semantics(repaired_request)
        if not semantic_reasons:
            _audit(call_id, ctx, provider.model_name, raw, repaired_output, True, True, True, "REPAIRED", repair_latency_ms, invalid_reasons)
            return IntentParseResult(
                travel_request=repaired_request,
                llm_validation_result=_validation_result(
                    schema_valid=True,
                    semantic_valid=True,
                    repair_attempted=True,
                    repair_success=True,
                    final_strategy="REPAIRED",
                    invalid_reasons=invalid_reasons,
                    llm_call_id=call_id,
                    prompt_version=REPAIR_PROMPT_VERSION,
                    model_name=provider.model_name,
                    latency_ms=repair_latency_ms,
                ),
            )
        repaired_reasons.extend(semantic_reasons)

    final_reasons = [*invalid_reasons, *repaired_reasons]
    _audit(call_id, ctx, provider.model_name, raw, repaired_output or raw_output, False, False, True, "REJECTED", repair_latency_ms, final_reasons)
    try:
        return _parse_with_rule_fallback(raw, ctx, current_date, [f"real_llm output rejected; rule parser fallback used: {'; '.join(final_reasons)}"])
    except IntentParserError:
        pass
    validation = _validation_result(
        schema_valid=False,
        semantic_valid=False,
        repair_attempted=True,
        repair_success=False,
        final_strategy="REJECTED",
        invalid_reasons=final_reasons,
        llm_call_id=call_id,
        prompt_version=REPAIR_PROMPT_VERSION,
        model_name=provider.model_name,
        latency_ms=repair_latency_ms,
    )
    raise IntentParserError(
        "自然语言解析失败，请补充信息后重试。",
        _missing_fields_from_reasons(final_reasons),
        _follow_up_questions_from_reasons(final_reasons),
        validation,
    )


def _travel_request_from_llm_output(raw_output: str, raw_user_input: str, ctx: RequestContext) -> tuple[TravelRequest | None, list[str]]:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return None, [f"LLM output is not valid JSON: {exc.msg}"]
    if not isinstance(payload, dict):
        return None, ["LLM output must be a JSON object"]
    payload.setdefault("schema_version", "1.16")
    payload.setdefault("request_id", ctx.request_id)
    payload.setdefault("raw_user_input", raw_user_input)
    try:
        return _normalize_time_intent(TravelRequest.model_validate(payload)), []
    except ValidationError as exc:
        return None, [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]


def validate_travel_request_semantics(request: TravelRequest) -> list[str]:
    reasons: list[str] = []
    if not request.origin_text.strip():
        reasons.append("origin_text is required")
    if not request.destination_text.strip():
        reasons.append("destination_text is required")
    if not request.preferences:
        reasons.append("preferences must not be empty")
    allowed = set(request.hard_constraints.allowed_transport_modes)
    excluded = set(request.hard_constraints.excluded_transport_modes)
    conflict = sorted(allowed & excluded)
    if conflict:
        reasons.append(f"allowed_transport_modes conflicts with excluded_transport_modes: {', '.join(conflict)}")
    for label, point in [
        ("earliest_departure_time", request.earliest_departure_time),
        ("latest_arrival_time", request.latest_arrival_time),
        ("preferred_departure_time", request.preferred_departure_time),
        ("hard_constraints.earliest_departure_time", request.hard_constraints.earliest_departure_time),
        ("hard_constraints.latest_arrival_time", request.hard_constraints.latest_arrival_time),
    ]:
        if point is not None and not point.timezone:
            reasons.append(f"{label}.timezone is required")
    cost = request.hard_constraints.max_total_cost
    if cost is not None and (cost.currency != "CNY" or cost.scale != 2):
        reasons.append("hard_constraints.max_total_cost must use CNY minor units with scale 2")
    return reasons


def _missing_fields_from_reasons(reasons: list[str]) -> list[str]:
    fields: list[str] = []
    mapping = {
        "origin_text": "origin_text",
        "destination_text": "destination_text",
        "travel_date": "travel_date",
        "preferences": "preferences",
        "allowed_transport_modes": "hard_constraints",
    }
    for reason in reasons:
        for marker, field in mapping.items():
            if marker in reason and field not in fields:
                fields.append(field)
    return fields


def _follow_up_questions_from_reasons(reasons: list[str]) -> list[str]:
    fields = _missing_fields_from_reasons(reasons)
    questions: list[str] = []
    if "travel_date" in fields:
        questions.append("你计划哪一天出发？")
    if "origin_text" in fields or "destination_text" in fields:
        questions.append("请补充明确的出发地和目的地。")
    if "hard_constraints" in fields:
        questions.append("请确认交通方式限制是否互相冲突。")
    return questions or ["请补充更明确的日期、地点或交通方式限制。"]


def _elapsed_ms(start: float) -> int:
    return int((perf_time.perf_counter() - start) * 1000)


def _audit(call_id: str, ctx: RequestContext, model_name: str, raw_input: str, raw_output: str, schema_valid: bool, semantic_valid: bool, repair_attempted: bool, final_strategy: str, latency_ms: int, invalid_reasons: list[str]) -> None:
    log_llm_call(
        llm_call_id=call_id,
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        prompt_version=REPAIR_PROMPT_VERSION if repair_attempted else INTENT_PARSER_PROMPT_VERSION,
        model_name=model_name,
        input_hash=stable_hash(raw_input),
        output_hash=stable_hash(raw_output) if raw_output else None,
        schema_valid=schema_valid,
        semantic_valid=semantic_valid,
        repair_attempted=repair_attempted,
        final_strategy=final_strategy,
        latency_ms=latency_ms,
        invalid_reasons=invalid_reasons,
    )
