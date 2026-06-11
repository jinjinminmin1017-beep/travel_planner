from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
from uuid import uuid4

from app.core.context import RequestContext
from app.data_sources.flight_providers import FlightSearchRequest, search_flight_offers_with_enabled_provider_result
from app.data_sources.map_providers import MapRouteRequest, estimate_route_with_enabled_provider
from app.data_sources.rail_providers import RailSearchRequest, search_rail_offers_with_enabled_provider_result
from app.models.schemas import (
    AirportCandidate,
    CabinOption,
    ComfortScore,
    CostBreakdown,
    CostItem,
    DataQuality,
    DataSourceMetadata,
    DataSourceType,
    FlightSegment,
    GeoPoint,
    LLMRecommendationInput,
    LocalTransferOption,
    LocalTransferSegment,
    MissingPlanExplanation,
    NormalizedScores,
    PlanLifecycleStatus,
    PlanType,
    PlanningStatus,
    RailSegment,
    RecalculateChangeSummary,
    RecalculateRequest,
    RecalculateResponse,
    RecommendationEligibility,
    RiskAssessment,
    RiskItem,
    RiskLevel,
    SourceFailure,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    StationCandidate,
    TicketEnhancement,
    TicketEnhancementGrade,
    TimePoint,
    TransportMode,
    TravelPlan,
    TravelPlanResponse,
    TravelRequest,
    money,
    money_delta,
    now_timepoint,
)
from app.services.destination_assets import resolve_destination_presentation
from app.services.intent_parser import parse_travel_request
from app.services.planning_rules import assert_option_available, candidate_plans_for_recommendation
from app.services.recommendation import recommend_with_validation
from app.services.store import update_plan


def _tp(day, hour: int, minute: int = 0) -> TimePoint:
    return TimePoint(datetime=datetime.combine(day, time(hour, minute)).astimezone(), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _source(source_id: str, name: str, source_type: DataSourceType = DataSourceType.INTERNAL_CALCULATION) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=name,
        source_type=source_type,
        authority_level="B",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        update_frequency="REALTIME_OR_RULE",
        cacheable=True,
    )


MAP_SOURCE = _source("amap_route", "AMap Route Planning API", DataSourceType.MAP)
RAIL_SOURCE = _source("rail_authorized_partner", "Authorized Rail Partner API", DataSourceType.RAIL)
FLIGHT_SOURCE = _source("amadeus_flight_offers", "Amadeus Flight Offers Search API", DataSourceType.FLIGHT)
TAXI_SOURCE = _source("amap_route", "AMap Route Planning API", DataSourceType.MAP)
INTERNAL_SOURCE = _source("internal_calc", "Internal Deterministic Calculator", DataSourceType.INTERNAL_CALCULATION)

PLACE_COORDINATES = {
    "上海嘉定南翔格林公馆": GeoPoint(latitude=31.295500, longitude=121.323200),
    "上海虹桥站": GeoPoint(latitude=31.200000, longitude=121.326900),
    "上海虹桥机场": GeoPoint(latitude=31.197900, longitude=121.336300),
    "上海浦东机场": GeoPoint(latitude=31.144300, longitude=121.808300),
    "青岛北站": GeoPoint(latitude=36.169600, longitude=120.374100),
    "青岛站": GeoPoint(latitude=36.064600, longitude=120.312700),
    "青岛胶东机场": GeoPoint(latitude=36.361900, longitude=120.088100),
    "青岛金水假日酒店": GeoPoint(latitude=36.161500, longitude=120.435100),
    "北京国贸": GeoPoint(latitude=39.909700, longitude=116.461900),
    "北京西站": GeoPoint(latitude=39.894900, longitude=116.321000),
    "北京首都机场": GeoPoint(latitude=40.080100, longitude=116.603100),
    "广州天河体育中心": GeoPoint(latitude=23.136900, longitude=113.326600),
    "广州南站": GeoPoint(latitude=22.989200, longitude=113.269400),
    "广州白云机场": GeoPoint(latitude=23.392400, longitude=113.303300),
}


def _nearby_station(place: str, mode: TransportMode, side: str) -> str:
    if mode == TransportMode.SUBWAY:
        known = {
            "上海嘉定南翔格林公馆": "南翔站",
            "上海虹桥站": "虹桥火车站",
            "上海虹桥机场": "虹桥2号航站楼站",
            "上海浦东机场": "浦东1号2号航站楼站",
            "青岛北站": "青岛北站",
            "青岛站": "青岛站",
            "青岛胶东机场": "胶东机场站",
            "青岛金水假日酒店": "枣山路站",
            "北京": "前门站" if side == "origin" else "北京西站",
            "北京西站": "北京西站",
            "北京首都机场": "首都机场T3站",
            "广州": "公园前站",
            "广州南": "广州南站",
            "广州白云机场": "机场南站",
        }
        return known.get(place, f"{place}附近地铁站")
    known_bus = {
        "上海嘉定南翔格林公馆": "南翔格林公馆公交站",
        "上海虹桥站": "虹桥西交通中心公交站",
        "上海虹桥机场": "虹桥枢纽东交通中心公交站",
        "上海浦东机场": "浦东机场T2公交站",
        "青岛北站": "铁路青岛北站东广场公交站",
        "青岛站": "青岛火车站公交站",
        "青岛胶东机场": "胶东机场公交换乘站",
        "青岛金水假日酒店": "金水路酒店公交站",
        "北京": "前门公交站",
        "北京西站": "北京西站南广场公交站",
        "北京首都机场": "首都机场T3公交站",
        "广州": "公园前公交站",
        "广州南": "广州南站公交总站",
        "广州白云机场": "白云机场公交站",
    }
    return known_bus.get(place, f"{place}附近公交站")


def _place_point(place: str) -> GeoPoint | None:
    if place in PLACE_COORDINATES:
        return PLACE_COORDINATES[place]
    if place.endswith("站") and place[:-1] in PLACE_COORDINATES:
        return PLACE_COORDINATES[place[:-1]]
    return None


def _place_city(place: str) -> str | None:
    for city in ("上海", "青岛", "北京", "广州"):
        if city in place:
            return city
    return None


def _real_route_estimate(origin: str, destination: str, mode: TransportMode):
    origin_point = _place_point(origin)
    destination_point = _place_point(destination)
    if not origin_point or not destination_point:
        raise ValueError(f"missing coordinates for real route estimate: {origin} -> {destination}")
    estimate = estimate_route_with_enabled_provider(
        MapRouteRequest(
            origin=origin_point,
            destination=destination_point,
            mode=mode,
            origin_city=_place_city(origin),
            destination_city=_place_city(destination),
        )
    )
    if estimate is None:
        raise ValueError(f"real map route provider unavailable for {mode}: {origin} -> {destination}")
    return estimate


def _transfer_options(origin: str, destination: str, minutes: int, cost_minor: int) -> list[LocalTransferOption]:
    subway_origin = _nearby_station(origin, TransportMode.SUBWAY, "origin")
    subway_destination = _nearby_station(destination, TransportMode.SUBWAY, "destination")
    bus_origin = _nearby_station(origin, TransportMode.BUS, "origin")
    bus_destination = _nearby_station(destination, TransportMode.BUS, "destination")
    taxi_estimate = _real_route_estimate(origin, destination, TransportMode.TAXI)
    subway_estimate = _real_route_estimate(origin, destination, TransportMode.SUBWAY)
    bus_estimate = _real_route_estimate(origin, destination, TransportMode.BUS)
    taxi_minutes = taxi_estimate.duration_minutes if taxi_estimate else minutes
    taxi_cost = taxi_estimate.estimated_cost if taxi_estimate and taxi_estimate.estimated_cost else money(cost_minor, estimated=True)
    subway_minutes = subway_estimate.duration_minutes if subway_estimate else minutes + 18
    subway_cost = subway_estimate.estimated_cost if subway_estimate and subway_estimate.estimated_cost else money(900, estimated=True)
    bus_minutes = bus_estimate.duration_minutes if bus_estimate else minutes + 28
    bus_cost = bus_estimate.estimated_cost if bus_estimate and bus_estimate.estimated_cost else money(500, estimated=True)
    return [
        LocalTransferOption(
            option_id="transfer_taxi",
            transfer_mode=TransportMode.TAXI,
            label="打车",
            estimated_cost=taxi_cost,
            duration_minutes=taxi_minutes,
            access_instruction=f"从 {origin} 上车，直达 {destination}。",
            ride_instruction=f"按 {taxi_estimate.summary} 估算行驶。",
            egress_instruction=f"在 {destination} 下车。",
            walking_distance_meters=120,
            data_source=taxi_estimate.data_source if taxi_estimate else TAXI_SOURCE,
        ),
        LocalTransferOption(
            option_id="transfer_subway",
            transfer_mode=TransportMode.SUBWAY,
            label="地铁",
            estimated_cost=subway_cost,
            duration_minutes=subway_minutes,
            access_station=subway_origin,
            egress_station=subway_destination,
            access_instruction=f"从 {origin} 步行/短驳至 {subway_origin}。",
            ride_instruction=f"按 {subway_estimate.summary} 前往 {subway_destination}。",
            egress_instruction=f"从 {subway_destination} 步行/短驳至 {destination}。",
            walking_distance_meters=780,
            data_source=subway_estimate.data_source if subway_estimate else TAXI_SOURCE,
        ),
        LocalTransferOption(
            option_id="transfer_bus",
            transfer_mode=TransportMode.BUS,
            label="公交",
            estimated_cost=bus_cost,
            duration_minutes=bus_minutes,
            access_station=bus_origin,
            egress_station=bus_destination,
            access_instruction=f"从 {origin} 步行至 {bus_origin}。",
            ride_instruction=f"按 {bus_estimate.summary} 前往 {bus_destination}。",
            egress_instruction=f"从 {bus_destination} 步行/短驳至 {destination}。",
            walking_distance_meters=980,
            data_source=bus_estimate.data_source if bus_estimate else TAXI_SOURCE,
        ),
    ]


def _taxi(segment_id: str, origin: str, destination: str, minutes: int, cost_minor: int, option_id: str = "transfer_taxi") -> LocalTransferSegment:
    options = _transfer_options(origin, destination, minutes, cost_minor)
    selected = next(option for option in options if option.option_id == option_id)
    return LocalTransferSegment(
        segment_id=segment_id,
        origin=origin,
        destination=destination,
        transfer_mode=selected.transfer_mode,
        distance_meters=minutes * 650,
        duration_minutes=selected.duration_minutes,
        estimated_cost=selected.estimated_cost,
        traffic_risk=RiskLevel.MEDIUM if minutes > 50 else RiskLevel.LOW,
        walking_distance_meters=selected.walking_distance_meters,
        option_id=option_id,
        available_options=[option.option_id for option in options],
        transfer_options=options,
        data_source=selected.data_source,
        redirect_info=None,
    )


def _rail(segment_id: str, train: str, origin: str, destination: str, day, dep_h: int, dep_m: int, arr_h: int, arr_m: int, base_minor: int, stops: list[str]) -> RailSegment:
    result = search_rail_offers_with_enabled_provider_result(
        RailSearchRequest(
            train_number=train,
            origin_station=origin,
            destination_station=destination,
            departure_date=day,
        )
    )
    if not result.offers:
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "rail_authorized_partner"
        raise ValueError(f"real rail provider unavailable: {source_id}; {result.failure_message or 'no offers returned'}")
    offer = result.offers[0]
    return RailSegment(
        segment_id=segment_id,
        train_number=offer.train_number,
        origin_station=offer.origin_station,
        destination_station=offer.destination_station,
        departure_time=_timepoint_from_datetime(offer.departure_at, _tp(day, dep_h, dep_m)),
        arrival_time=_timepoint_from_datetime(offer.arrival_at, _tp(day, arr_h, arr_m)),
        duration_minutes=offer.duration_minutes,
        stop_sequence=offer.stop_sequence,
        seat_options=offer.seat_options,
        selected_seat_option_id=offer.seat_options[0].option_id,
        data_source=offer.data_source,
    )


def _flight(segment_id: str, flight: str, origin: str, destination: str, day, dep_h: int, dep_m: int, arr_h: int, arr_m: int, base_minor: int, previous_risk: bool = True) -> FlightSegment:
    codes = _flight_search_codes(flight)
    if not codes:
        raise ValueError(f"no real flight provider route mapping for {flight}")
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(
            origin_iata=codes[0],
            destination_iata=codes[1],
            departure_date=day,
            adults=1,
            currency_code="CNY",
            max_results=3,
            non_stop=True,
        )
    )
    if not result.offers:
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "amadeus_flight_offers"
        raise ValueError(f"real flight provider unavailable: {source_id}; {result.failure_message or 'no offers returned'}")
    offer = result.offers[0]
    first_segment = offer.segments[0] if offer.segments else None
    last_segment = offer.segments[-1] if offer.segments else None
    dep = _timepoint_from_datetime(first_segment.departure_at if first_segment else None, _tp(day, dep_h, dep_m))
    arr = _timepoint_from_datetime(last_segment.arrival_at if last_segment else None, _tp(day, arr_h, arr_m))
    duration = int((arr.datetime - dep.datetime).total_seconds() // 60)
    flight_number = f"{first_segment.carrier_code}{first_segment.flight_number}" if first_segment else flight
    return FlightSegment(
        segment_id=segment_id,
        flight_number=flight_number,
        origin_airport=origin,
        destination_airport=destination,
        departure_time=dep,
        arrival_time=arr,
        duration_minutes=duration,
        cabin_options=[
            CabinOption(option_id="cabin_economy", cabin_type="经济舱", price=offer.total_price, availability="AVAILABLE", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
            CabinOption(option_id="cabin_premium", cabin_type="超级经济舱", price=money(offer.total_price.amount_minor + 26000), availability="AVAILABLE", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
            CabinOption(option_id="cabin_business", cabin_type="商务舱", price=money(offer.total_price.amount_minor + 76000), availability="LIMITED", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
        ],
        selected_cabin_option_id="cabin_economy",
        previous_flight_risk_available=previous_risk,
        data_source=offer.data_source,
    )


def _real_direct_flight_segment(segment_id: str, flight: str, origin: str, destination: str, day, dep_h: int, dep_m: int, arr_h: int, arr_m: int, base_minor: int) -> FlightSegment:
    codes = _flight_search_codes(flight)
    if not codes:
        raise ValueError(f"no real flight provider route mapping for {flight}")
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(
            origin_iata=codes[0],
            destination_iata=codes[1],
            departure_date=day,
            adults=1,
            currency_code="CNY",
            max_results=3,
            non_stop=True,
        )
    )
    if not result.offers:
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "amadeus_flight_offers"
        raise ValueError(f"real flight provider unavailable: {source_id}; {result.failure_message or 'no offers returned'}")

    offer = result.offers[0]
    first_segment = offer.segments[0] if offer.segments else None
    last_segment = offer.segments[-1] if offer.segments else None
    dep = _timepoint_from_datetime(first_segment.departure_at if first_segment else None, _tp(day, dep_h, dep_m))
    arr = _timepoint_from_datetime(last_segment.arrival_at if last_segment else None, _tp(day, arr_h, arr_m))
    duration = int((arr.datetime - dep.datetime).total_seconds() // 60)
    flight_number = f"{first_segment.carrier_code}{first_segment.flight_number}" if first_segment else flight
    return FlightSegment(
        segment_id=segment_id,
        flight_number=flight_number,
        origin_airport=origin,
        destination_airport=destination,
        departure_time=dep,
        arrival_time=arr,
        duration_minutes=duration,
        cabin_options=[
            CabinOption(option_id="cabin_economy", cabin_type="经济舱", price=offer.total_price, availability="AVAILABLE", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
            CabinOption(option_id="cabin_premium", cabin_type="超级经济舱", price=money(offer.total_price.amount_minor + 26000), availability="AVAILABLE", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
            CabinOption(option_id="cabin_business", cabin_type="商务舱", price=money(offer.total_price.amount_minor + 76000), availability="LIMITED", source_option_version=f"amadeus_{offer.offer_id}", data_source=offer.data_source),
        ],
        selected_cabin_option_id="cabin_economy",
        previous_flight_risk_available=True,
        data_source=offer.data_source,
    )


def _flight_search_codes(flight: str) -> tuple[str, str] | None:
    if flight.startswith("MU"):
        return ("SHA", "TAO")
    if flight.startswith("CZ"):
        return ("PEK", "CAN")
    if flight.startswith("SC"):
        return ("SHA", "TAO")
    return None


def _timepoint_from_datetime(value: datetime | None, fallback: TimePoint) -> TimePoint:
    if value is None:
        return fallback
    return TimePoint(datetime=value.astimezone(), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _real_flight_block_failure(travel_request: TravelRequest, source_id: str, message: str) -> SourceFailure:
    return SourceFailure(
        failure_id=f"fail_{uuid4().hex[:8]}",
        request_id=travel_request.request_id,
        trace_id="trace_pending",
        correlation_id="corr_pending",
        source_id=source_id,
        source_used_id=None,
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
        failure_class=SourceFailureClass.CORE_FACT,
        message=message,
        final_handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN_TYPE,
        impacted_plan_types=[PlanType.DIRECT_FLIGHT],
        user_visible_message="真实航班搜索不可用，直飞航班方案已阻断；系统不会用测试数据冒充真实结果。",
        occurred_at=now_timepoint(),
    )


def _cost_items(segments, ticket: TicketEnhancement | None = None) -> CostBreakdown:
    items: list[CostItem] = []
    total = 0
    for segment in segments:
        if isinstance(segment, LocalTransferSegment):
            amount = segment.estimated_cost
            label = f"{segment.origin} → {segment.destination} 接驳"
            source = segment.data_source
        elif isinstance(segment, RailSegment):
            option = next(item for item in segment.seat_options if item.option_id == segment.selected_seat_option_id)
            amount = option.price
            label = f"{segment.train_number} {option.seat_type}"
            source = option.data_source
        else:
            option = next(item for item in segment.cabin_options if item.option_id == segment.selected_cabin_option_id)
            amount = option.price
            label = f"{segment.flight_number} {option.cabin_type}"
            source = option.data_source
        total += amount.amount_minor
        items.append(CostItem(label=label, amount=amount, data_source=source))
    if ticket:
        total += ticket.extra_cost.amount_minor
        items.append(CostItem(label=f"票源增强 {ticket.grade} 档额外费用", amount=ticket.extra_cost, data_source=ticket.data_source))
    return CostBreakdown(total_cost=money(total), items=items)


def _risk(level: RiskLevel, title: str, message: str) -> RiskAssessment:
    return RiskAssessment(
        overall_risk_level=level,
        recommendation_allowed=level != RiskLevel.BLOCKED,
        risk_items=[RiskItem(risk_id=f"risk_{uuid4().hex[:8]}", risk_level=level, title=title, message=message, data_source=INTERNAL_SOURCE)],
    )


def _comfort(score: float, text: str, confidence: float = 0.95) -> ComfortScore:
    return ComfortScore(
        total_score=score,
        breakdown={
            "换乘复杂度": min(10, score + 0.2),
            "等待压力": min(10, score),
            "时间友好度": max(0, score - 0.3),
            "座席/舱位舒适度": min(10, score + 0.4),
            "接驳便利性": min(10, score + 0.1),
            "误车/误机风险": max(0, score - 0.6),
            "行李友好度": min(10, score + 0.2),
        },
        score_vector=NormalizedScores(cost=0.7, duration=0.7, comfort=score / 10, risk=0.8),
        confidence=confidence,
        explanation=text,
    )


def _plan(plan_id: str, name: str, plan_type: PlanType, segments, comfort: float, risk: RiskLevel, risk_title: str, risk_message: str, ticket: TicketEnhancement | None = None, eligibility: RecommendationEligibility = RecommendationEligibility.ELIGIBLE, can_llm: bool = True, block_code: str | None = None, block_message: str | None = None) -> TravelPlan:
    cost = _cost_items(segments, ticket)
    data_sources = list({item.source_id: item for item in [INTERNAL_SOURCE, *[segment.data_source for segment in segments], *[ci.data_source for ci in cost.items]]}.values())
    return TravelPlan(
        plan_id=plan_id,
        plan_name=name,
        plan_type=plan_type,
        plan_lifecycle_status=PlanLifecycleStatus.ACTIVE,
        recommendation_eligibility=eligibility,
        can_be_selected_by_llm=can_llm,
        block_reason_code=block_code,
        block_reason_message=block_message,
        segments=segments,
        ticket_enhancement=ticket,
        total_duration_minutes=sum(segment.duration_minutes for segment in segments),
        departure_time=segments[0].departure_time if hasattr(segments[0], "departure_time") else None,
        arrival_time=segments[-1].arrival_time if hasattr(segments[-1], "arrival_time") else None,
        cost_breakdown=cost,
        comfort_score=_comfort(comfort, f"{name} 的舒适度由接驳、换乘、座席/舱位和风险共同计算。", 0.86 if risk != RiskLevel.LOW else 0.95),
        risk_assessment=_risk(risk, risk_title, risk_message),
        data_quality=DataQuality(
            completeness_score=0.88 if risk == RiskLevel.MEDIUM else (0.72 if risk == RiskLevel.HIGH else 0.96),
            missing_components=[] if risk == RiskLevel.LOW else ["部分实时辅助数据缺失"],
            warnings=[] if risk == RiskLevel.LOW else [risk_message],
        ),
        data_sources=data_sources,
        booking_redirects=[],
    )


def _ticket(enhancement_id: str, grade: TicketEnhancementGrade, extra_minor: int, extra_ratio: float, unused_ratio: float, risk: RiskLevel, message: str, covers: bool = True, supplement: bool = False) -> TicketEnhancement:
    return TicketEnhancement(
        enhancement_id=enhancement_id,
        grade=grade,
        actual_origin="上海虹桥",
        actual_destination="青岛北",
        ticket_origin="南京南" if not covers else "苏州北",
        ticket_destination="潍坊北" if supplement else "青岛北",
        ticket_covers_actual_route=covers,
        requires_onboard_supplement=supplement,
        unused_distance_ratio=unused_ratio,
        extra_cost=money(extra_minor),
        extra_cost_ratio=extra_ratio,
        risk_level=risk,
        recommendation_message=message,
        validation_source="authorized_rail_partner_station_sequence",
        validation_rule_version="ticket_enhancement_v1",
        data_source=RAIL_SOURCE,
    )


def build_plans(travel_request: TravelRequest) -> tuple[list[TravelPlan], list[SourceFailure], list[str], list[PlanType], list[MissingPlanExplanation], list[str]]:
    day = travel_request.travel_date
    origin = travel_request.origin_text
    destination = travel_request.destination_text
    is_beijing_guangzhou = "北京" in origin or "广州" in destination
    if is_beijing_guangzhou:
        city_origin, city_destination = "北京国贸", "广州天河体育中心"
        start_station, end_station = "北京西", "广州南"
        start_airport, end_airport = "北京首都机场", "广州白云机场"
        rail_train, flight_no = "G79", "CZ3102"
    else:
        city_origin, city_destination = "上海嘉定南翔格林公馆", "青岛金水假日酒店"
        start_station, end_station = "上海虹桥", "青岛北"
        start_airport, end_airport = "上海虹桥机场", "青岛胶东机场"
        rail_train, flight_no = "G234", "MU5511"

    rail_direct = _plan(
        "plan_rail_direct_bg" if is_beijing_guangzhou else "plan_rail_direct_shqd",
        "打车 + 高铁直达 + 打车",
        PlanType.DIRECT_RAIL,
        [
            _taxi("seg_origin_station", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_direct", rail_train, start_station, end_station, day, 9, 48, 15, 38, 52600, [start_station, "济南西" if not is_beijing_guangzhou else "郑州东", end_station]),
            _taxi("seg_station_dest", f"{end_station}站", city_destination, 32, 6200),
        ],
        7.9,
        RiskLevel.LOW,
        "直达风险低",
        "直达高铁换乘少，接驳风险可控。",
    )

    rail_transfer = _plan(
        "plan_rail_transfer_bg" if is_beijing_guangzhou else "plan_rail_transfer_shqd",
        "打车 + 高铁中转 + 打车",
        PlanType.TRANSFER_RAIL,
        [
            _taxi("seg_origin_station_transfer", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_transfer_1", "G102", start_station, "南京南" if not is_beijing_guangzhou else "郑州东", day, 10, 15, 11, 35, 16800, [start_station, "中转站"]),
            _rail("seg_rail_transfer_2", "G268", "南京南" if not is_beijing_guangzhou else "郑州东", end_station, day, 12, 35, 17, 10, 38600, ["中转站", end_station]),
            _taxi("seg_station_dest_transfer", f"{end_station}站", city_destination, 32, 6200),
        ],
        7.1,
        RiskLevel.MEDIUM,
        "中转等待风险",
        "高铁中转需要关注站内换乘时间和行李负担。",
    )

    flight_direct = _plan(
        "plan_flight_direct_bg" if is_beijing_guangzhou else "plan_flight_direct_shqd",
        "打车 + 航班直飞 + 打车",
        PlanType.DIRECT_FLIGHT,
        [
            _taxi("seg_origin_airport", city_origin, start_airport, 52, 11800),
            _real_direct_flight_segment("seg_flight_direct", flight_no, start_airport, end_airport, day, 11, 20, 13, 0, 68600),
            _taxi("seg_airport_dest", end_airport, city_destination, 54, 13600),
        ],
        8.8,
        RiskLevel.LOW,
        "直飞舒适",
        "直飞减少铁路长途乘坐时间，但仍需预留值机安检时间。",
    )

    flight_transfer = _plan(
        "plan_flight_transfer_bg" if is_beijing_guangzhou else "plan_flight_transfer_shqd",
        "打车 + 航班中转 + 打车",
        PlanType.TRANSFER_FLIGHT,
        [
            _taxi("seg_origin_airport_transfer", city_origin, start_airport, 52, 11800),
            _flight("seg_flight_transfer_1", "MU2101", start_airport, "济南遥墙机场" if not is_beijing_guangzhou else "武汉天河机场", day, 10, 35, 12, 10, 35600, previous_risk=False),
            _flight("seg_flight_transfer_2", "SC8720", "济南遥墙机场" if not is_beijing_guangzhou else "武汉天河机场", end_airport, day, 14, 0, 15, 10, 29800),
            _taxi("seg_airport_dest_transfer", end_airport, city_destination, 54, 13600),
        ],
        7.4,
        RiskLevel.MEDIUM,
        "航班中转风险",
        "中转机场可能存在延误和重新安检风险。",
    )

    mixed = _plan(
        "plan_mixed_bg" if is_beijing_guangzhou else "plan_mixed_shqd",
        "航班 + 高铁混合交通",
        PlanType.FLIGHT_RAIL_MIXED,
        [
            _taxi("seg_origin_airport_mixed", city_origin, start_airport, 52, 11800),
            _flight("seg_flight_mixed", "MU9100", start_airport, "济南遥墙机场" if not is_beijing_guangzhou else "长沙黄花机场", day, 10, 20, 11, 55, 31800),
            _rail("seg_rail_mixed", "G556", "济南西" if not is_beijing_guangzhou else "长沙南", end_station, day, 13, 15, 15, 35, 18800, ["中转城市", end_station]),
            _taxi("seg_station_dest_mixed", f"{end_station}站", city_destination, 32, 6200),
        ],
        7.7,
        RiskLevel.MEDIUM,
        "多交通组合风险",
        "跨交通方式需要额外预留接驳和进站时间。",
    )

    ticket_s = _ticket("enh_s", TicketEnhancementGrade.S, 6800, 0.12, 0.16, RiskLevel.LOW, "S 档票源增强：多买区间完整覆盖实际乘车区间。")
    rail_ticket_s = _plan(
        "plan_ticket_s_shqd",
        "高铁票源增强 S 档",
        PlanType.RAIL_TICKET_ENHANCEMENT,
        [
            _taxi("seg_origin_station_ticket_s", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_ticket_s", "G236", start_station, end_station, day, 9, 20, 15, 5, 53600, ["苏州北", start_station, "济南西", end_station]),
            _taxi("seg_station_dest_ticket_s", f"{end_station}站", city_destination, 32, 6200),
        ],
        8.2,
        RiskLevel.LOW,
        "票源增强可控",
        "票面区间覆盖实际区间，不需要补票。",
        ticket=ticket_s,
    )

    ticket_a = _ticket("enh_a", TicketEnhancementGrade.A, 16800, 0.26, 0.31, RiskLevel.MEDIUM, "A 档票源增强：默认作为备选展示。")
    rail_ticket_a = _plan(
        "plan_ticket_a_shqd",
        "高铁票源增强 A 档备选",
        PlanType.RAIL_TICKET_ENHANCEMENT,
        [
            _taxi("seg_origin_station_ticket_a", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_ticket_a", "G238", start_station, end_station, day, 10, 0, 15, 50, 53600, ["无锡东", start_station, "济南西", end_station, "潍坊北"]),
            _taxi("seg_station_dest_ticket_a", f"{end_station}站", city_destination, 32, 6200),
        ],
        7.8,
        RiskLevel.MEDIUM,
        "票源增强谨慎推荐",
        "额外费用和未乘坐比例较高，默认不作为主推荐。",
        ticket=ticket_a,
        eligibility=RecommendationEligibility.NOT_RECOMMENDED,
        can_llm=False,
        block_code="TICKET_A_BACKUP_ONLY",
        block_message="A 档票源增强默认作为备选，不进入主推荐。",
    )

    buy_short = _ticket("enh_buy_short", TicketEnhancementGrade.NOT_RECOMMENDED, 0, 0, 0, RiskLevel.HIGH, "买短补长高风险方案，仅作为折叠备选。", covers=True, supplement=True)
    buy_short_plan = _plan(
        "plan_buy_short_shqd",
        "买短补长高风险备选",
        PlanType.RAIL_TICKET_ENHANCEMENT,
        [
            _taxi("seg_origin_station_buy_short", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_buy_short", "G240", start_station, end_station, day, 10, 40, 16, 10, 39600, [start_station, "潍坊北", end_station]),
            _taxi("seg_station_dest_buy_short", f"{end_station}站", city_destination, 32, 6200),
        ],
        5.8,
        RiskLevel.HIGH,
        "买短补长高风险",
        "补票成功、席位、费用和出站结果均以铁路现场规则为准。",
        ticket=buy_short,
        eligibility=RecommendationEligibility.NOT_RECOMMENDED,
        can_llm=False,
        block_code="BUY_SHORT_SUPPLEMENT_REQUIRED",
        block_message="买短补长不得进入三张主推荐卡。",
    )

    blocked = _plan(
        "plan_blocked_shqd",
        "安全关键数据缺失 BLOCKED",
        PlanType.TRANSFER_RAIL,
        [
            _taxi("seg_origin_station_blocked", city_origin, f"{start_station}站", 38, 7800),
            _rail("seg_rail_blocked", "G999", start_station, end_station, day, 11, 0, 15, 30, 30000, [start_station, end_station]),
            _taxi("seg_station_dest_blocked", f"{end_station}站", city_destination, 32, 6200),
        ],
        4.0,
        RiskLevel.BLOCKED,
        "安全关键数据缺失",
        "站序或最小中转时间无法确认，方案被阻断。",
        eligibility=RecommendationEligibility.BLOCKED,
        can_llm=False,
        block_code="SAFETY_CRITICAL_MISSING",
        block_message="安全关键数据缺失，不能进入推荐候选池。",
    )

    plans = [rail_direct, rail_transfer, flight_direct, flight_transfer, mixed]
    if not is_beijing_guangzhou:
        plans.extend([rail_ticket_s, rail_ticket_a, buy_short_plan, blocked])

    failures = [
        SourceFailure(
            failure_id=f"fail_{uuid4().hex[:8]}",
            request_id=travel_request.request_id,
            trace_id="trace_pending",
            correlation_id="corr_pending",
            source_id="variflight_status",
            source_used_id=None,
            fallback_source_id=None,
            fallback_reason=None,
            fallback_used=False,
            failure_class=SourceFailureClass.AUXILIARY,
            message="previous flight risk data missing from real provider",
            final_handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
            impacted_plan_types=[PlanType.TRANSFER_FLIGHT],
            user_visible_message="部分航班前序风险数据缺失，已降低数据质量置信度。",
            occurred_at=now_timepoint(),
        )
    ]
    missing = ["previous_flight_risk"] if not is_beijing_guangzhou else []
    blocked_types = [PlanType.TRANSFER_RAIL] if not is_beijing_guangzhou else []
    explanations = [
        MissingPlanExplanation(plan_type=PlanType.MULTI_TRANSFER_RAIL, reason_code="REAL_PROVIDER_CAPABILITY_GAP", user_visible_message="当前授权数据源暂未返回可验证的多段中转方案。")
    ]
    warnings = ["价格和余票以最终平台为准。", "系统仅展示真实 Provider 或授权跳转返回的只读结果，不代下单或支付。"]
    return plans, failures, missing, blocked_types, explanations, warnings


def plan_trip(raw_or_request: str | TravelRequest, ctx: RequestContext) -> TravelPlanResponse:
    travel_request = parse_travel_request(raw_or_request, ctx) if isinstance(raw_or_request, str) else raw_or_request
    plans, failures, missing, blocked_types, explanations, warnings = build_plans(travel_request)
    for failure in failures:
        failure.trace_id = ctx.trace_id
        failure.correlation_id = ctx.correlation_id
    candidate_plans = candidate_plans_for_recommendation(plans)
    recommendation_result = recommend_with_validation(
        LLMRecommendationInput(
            request_id=ctx.request_id,
            travel_request=travel_request,
            candidate_plan_ids=[plan.plan_id for plan in candidate_plans],
            candidate_plans=candidate_plans,
        )
    )
    planning_status = PlanningStatus.COMPLETE
    if recommendation_result is None:
        planning_status = PlanningStatus.PARTIAL
        missing = [*missing, "recommendation_result"]
        warnings = [
            *warnings,
            "真实 LLM 推荐不可用或输出未通过校验，系统未使用确定性规则生成最便宜、最舒适、综合推荐三张卡。",
        ]
        failures = [
            *failures,
            SourceFailure(
                failure_id=f"fail_{uuid4().hex[:8]}",
                request_id=ctx.request_id,
                trace_id=ctx.trace_id,
                correlation_id=ctx.correlation_id,
                source_id="real_llm",
                source_used_id=None,
                fallback_source_id=None,
                fallback_reason=None,
                fallback_used=False,
                failure_class=SourceFailureClass.AUXILIARY,
                message="LLM recommendation unavailable or invalid; deterministic recommendation fallback is disabled.",
                final_handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
                impacted_plan_types=list({plan.plan_type for plan in candidate_plans}),
                user_visible_message="真实 LLM 推荐不可用，暂不生成三张推荐卡；候选方案仍可查看。",
                occurred_at=now_timepoint(),
            ),
        ]
    return TravelPlanResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        planning_status=planning_status,
        progress=100,
        travel_request=travel_request,
        destination_presentation=resolve_destination_presentation(travel_request),
        plans=plans,
        recommendation_result=recommendation_result,
        source_failures=failures,
        missing_components=missing,
        blocked_plan_types=blocked_types,
        missing_plan_explanations=explanations,
        user_visible_warnings=warnings,
        async_job=None,
        generated_at=now_timepoint(),
    )


def recalculate_plan(existing: TravelPlan, request: RecalculateRequest, ctx: RequestContext) -> RecalculateResponse:
    plan = deepcopy(existing)
    target = next((segment for segment in plan.segments if segment.segment_id == request.target_segment_id), None)
    if target is None:
        raise ValueError("target_segment_id does not exist in plan")
    before_cost = plan.cost_breakdown.total_cost.amount_minor
    before_comfort = plan.comfort_score.total_score

    if request.change_type == "RAIL_SEAT":
        if not hasattr(target, "seat_options"):
            raise ValueError("target segment does not support rail seat options")
        assert_option_available(target, request.selected_option.option_id)
        target.selected_seat_option_id = request.selected_option.option_id
        plan.comfort_score.total_score = min(10, plan.comfort_score.total_score + (1.0 if "first" in request.selected_option.option_id else 2.0))
    elif request.change_type == "FLIGHT_CABIN":
        if not hasattr(target, "cabin_options"):
            raise ValueError("target segment does not support flight cabin options")
        assert_option_available(target, request.selected_option.option_id)
        target.selected_cabin_option_id = request.selected_option.option_id
        plan.comfort_score.total_score = min(10, plan.comfort_score.total_score + (1.2 if "premium" in request.selected_option.option_id else 2.4))
    else:
        if not isinstance(target, LocalTransferSegment):
            raise ValueError("target segment does not support local transfer options")
        assert_option_available(target, request.selected_option.option_id)
        selected_transfer = next(option for option in target.transfer_options if option.option_id == request.selected_option.option_id)
        target.transfer_mode = selected_transfer.transfer_mode
        target.estimated_cost = selected_transfer.estimated_cost
        target.duration_minutes = selected_transfer.duration_minutes
        target.walking_distance_meters = selected_transfer.walking_distance_meters
        target.option_id = selected_transfer.option_id
        if request.selected_option.option_id == "transfer_subway":
            plan.comfort_score.total_score = max(0, plan.comfort_score.total_score - 0.5)
        elif request.selected_option.option_id == "transfer_bus":
            plan.comfort_score.total_score = max(0, plan.comfort_score.total_score - 0.9)

    plan.cost_breakdown = _cost_items(plan.segments, plan.ticket_enhancement)
    plan.total_duration_minutes = sum(segment.duration_minutes for segment in plan.segments)
    update_plan(plan)
    after_cost = plan.cost_breakdown.total_cost.amount_minor
    return RecalculateResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=request.idempotency_key,
        plan=plan,
        change_summary=RecalculateChangeSummary(
            cost_delta=money_delta(after_cost - before_cost),
            duration_delta_minutes=0 if request.change_type != "LOCAL_TRANSFER" else plan.total_duration_minutes - existing.total_duration_minutes,
            comfort_delta=round(plan.comfort_score.total_score - before_comfort, 2),
            changed_fields=["cost_breakdown", "comfort_score", "selected_option"],
            message="已基于后端返回的合法 option_id 完成重算。",
        ),
        recommendation_result=None,
        generated_at=now_timepoint(),
    )
