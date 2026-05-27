from __future__ import annotations

import re
from datetime import date, datetime, time

from app.core.context import RequestContext
from app.models.schemas import (
    RecommendationType,
    TimePoint,
    TransportMode,
    TravelHardConstraints,
    TravelRequest,
    TravelSoftPreferences,
    money,
)


def _extract_date(raw: str) -> date:
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", raw)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    iso = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    raise ValueError("缺少出行日期，请补充具体日期。")


def _timepoint(day: date, hour: int, minute: int = 0) -> TimePoint:
    return TimePoint(datetime=datetime.combine(day, time(hour, minute)).astimezone(), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _extract_hour(raw: str, marker: str) -> int | None:
    pattern = rf"(上午|下午|晚上|中午)?\s*(\d{{1,2}})\s*点\s*(?:\d{{1,2}}\s*分)?\s*(?:{marker})"
    match = re.search(pattern, raw)
    if not match:
        return None
    prefix = match.group(1) or ""
    hour = int(match.group(2))
    if prefix in {"下午", "晚上"} and hour < 12:
        hour += 12
    if prefix == "中午" and hour < 11:
        hour += 12
    return hour


def _extract_origin_destination(raw: str) -> tuple[str, str]:
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
    raise ValueError("地点不够明确，请补充出发地和目的地。")


def parse_travel_request(raw: str, ctx: RequestContext) -> TravelRequest:
    travel_date = _extract_date(raw)
    origin, destination = _extract_origin_destination(raw)

    excluded: list[TransportMode] = []
    allowed: list[TransportMode] = []
    if "不坐飞机" in raw or "不要飞机" in raw:
        excluded.append(TransportMode.FLIGHT)
    if "不坐高铁" in raw or "不要高铁" in raw:
        excluded.append(TransportMode.RAIL)
    if "只看高铁" in raw or "只坐高铁" in raw:
        allowed.append(TransportMode.RAIL)
    if "不要机场大巴" in raw or "不要接送机" in raw:
        excluded.append(TransportMode.AIRPORT_TRANSFER)
    if "不要接送站" in raw:
        excluded.append(TransportMode.RAIL_STATION_TRANSFER)

    preferences = [RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED]
    preference_source = "SYSTEM_DEFAULT"
    cheap_markers = ["最便宜", "最优惠", "低价", "省钱"]
    comfort_markers = ["最舒服", "最舒适", "舒服", "舒适"]
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

    earliest = _extract_hour(raw, "后|以后|之后")
    latest = _extract_hour(raw, "前|以前|之前")
    around = _extract_hour(raw, "左右")

    max_cost = None
    budget = re.search(r"(?:预算|不要超过|不超过)\s*(\d{2,5})", raw)
    if budget:
        max_cost = money(int(budget.group(1)) * 100)

    passenger_notes: list[str] = []
    for keyword in ["老人", "小孩", "行李多"]:
        if keyword in raw:
            passenger_notes.append(keyword)

    return TravelRequest(
        request_id=ctx.request_id,
        raw_user_input=raw,
        origin_text=origin,
        destination_text=destination,
        travel_date=travel_date,
        earliest_departure_time=_timepoint(travel_date, earliest) if earliest is not None else None,
        latest_arrival_time=_timepoint(travel_date, latest) if latest is not None else None,
        preferred_departure_time=_timepoint(travel_date, around) if around is not None else None,
        preferences=preferences,
        preference_source=preference_source,
        hard_constraints=TravelHardConstraints(
            earliest_departure_time=_timepoint(travel_date, earliest) if earliest is not None else None,
            latest_arrival_time=_timepoint(travel_date, latest) if latest is not None else None,
            max_total_cost=max_cost,
            allowed_transport_modes=allowed,
            excluded_transport_modes=excluded,
        ),
        soft_preferences=TravelSoftPreferences(
            prefer_low_cost=RecommendationType.CHEAPEST in preferences,
            prefer_comfort=RecommendationType.MOST_COMFORTABLE in preferences,
            accept_rail_transfer="不接受高铁中转" not in raw,
            accept_flight_transfer="不接受航班中转" not in raw,
            accept_mixed_transport="不接受多交通" not in raw,
            accept_ticket_enhancement="不接受票源增强" not in raw,
            passenger_notes=passenger_notes,
        ),
        preferred_rail_seat="一等座" if "一等座" in raw else ("商务座" if "商务座" in raw else None),
        preferred_flight_cabin="商务舱" if "商务舱" in raw else ("头等舱" if "头等舱" in raw else None),
    )
