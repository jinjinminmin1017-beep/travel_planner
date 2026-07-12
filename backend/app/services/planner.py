from __future__ import annotations

import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from app.core.context import RequestContext
from app.data_sources.flight_providers import FlightOffer, FlightSearchRequest, search_flight_offers_with_enabled_provider_result
from app.data_sources.map_providers import MapRouteRequest, estimate_route_with_enabled_provider_result
from app.data_sources.rail_providers import RailOffer, RailSearchRequest, search_rail_offers_with_enabled_provider_result
from app.models.schemas import (
    AirportCandidate,
    CabinOption,
    DataSourceMetadata,
    DataSourceType,
    FlightSegment,
    GeoPoint,
    LLMRecommendationInput,
    LocalTransferOption,
    LocalTransferSegment,
    MissingPlanExplanation,
    PlanLifecycleStatus,
    PlanType,
    PlanningStatus,
    RailSegment,
    RecalculateChangeSummary,
    RecalculateRequest,
    RecalculateResponse,
    RecommendationEligibility,
    RecommendationResult,
    RiskLevel,
    SourceFailure,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    StationCandidate,
    TicketEnhancement,
    TimePoint,
    TransportMode,
    TravelPlan,
    TravelPlanResponse,
    TravelRequest,
    money,
    money_delta,
    now_timepoint,
)
from app.services.candidate_generator import generate_candidate_plan_pool
from app.services.cost_comfort_risk_engine import (
    build_comfort_score,
    build_data_quality,
    build_risk_assessment,
    calculate_cost_breakdown,
    refresh_plan_cost_and_quality,
)
from app.services.constraints.relaxation_selector import build_constraint_analysis
from app.services.destination_assets import resolve_destination_presentation
from app.services.flight_planning_engine import FlightPlanSpec
from app.services.intent_parser import parse_travel_request
from app.services.local_transfer_engine import build_local_transfer_segment
from app.services.location_resolver import (
    airport_candidates_for_city,
    airport_iata_for_candidate,
    nearby_transit_stop,
    planning_nodes_for_request,
    resolve_location_city,
    resolve_location_point,
    transfer_station_candidates_between,
)
from app.services.planning_rules import assert_option_available
from app.services.rail_planning_engine import RailPlanSpec, TicketEnhancementSpec
from app.services.recommendation import recommend_with_validation
from app.services.result_set_preferences import apply_rail_seat_to_result_set
from app.services.store import get_response_for_plan, update_plan

logger = logging.getLogger("app.planner.rail")


SHANGHAI_TZ = timezone(timedelta(hours=8))


def _as_shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def _tp(day, hour: int, minute: int = 0) -> TimePoint:
    return TimePoint(datetime=datetime.combine(day, time(hour, minute), tzinfo=SHANGHAI_TZ), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _source(source_id: str, name: str, source_type: DataSourceType = DataSourceType.INTERNAL_CALCULATION) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=name,
        source_type=source_type,
        authority_level="B",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
    )


MAP_SOURCE = _source("amap_route", "AMap Route Planning API", DataSourceType.MAP)
RAIL_SOURCE = _source("rail_12306_public_query", "12306 Public Ticket Query", DataSourceType.RAIL)
FLIGHT_SOURCE = _source("airline_public_query", "Official Airline Public Flight Query", DataSourceType.FLIGHT)
TAXI_SOURCE = _source("amap_route", "AMap Route Planning API", DataSourceType.MAP)
INTERNAL_SOURCE = _source("internal_calc", "Internal Deterministic Calculator", DataSourceType.INTERNAL_CALCULATION)


@dataclass
class PlanningIssueCollector:
    travel_request: TravelRequest
    failures: list[SourceFailure] = field(default_factory=list)
    missing_components: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_missing(self, component: str) -> None:
        if component not in self.missing_components:
            self.missing_components.append(component)

    def add_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)

    def has_rail_rate_limit(self) -> bool:
        return any(
            failure.source_id == "rail_12306_public_query" and failure.error_code == "RAIL_PROVIDER_RATE_LIMITED"
            for failure in self.failures
        )

    def add_source_failure(
        self,
        *,
        source_id: str,
        adapter_name: str,
        failure_class: SourceFailureClass,
        handling_strategy: SourceFailureHandlingStrategy,
        message: str,
        user_visible_message: str,
        impacted_plan_types: list[PlanType],
        error_code: str,
        source_used_id: str | None,
        fallback_source_id: str | None,
        fallback_reason: str | None,
        fallback_used: bool,
    ) -> None:
        self.failures.append(
            SourceFailure(
                failure_id=f"fail_{uuid4().hex[:8]}",
                request_id=self.travel_request.request_id,
                trace_id="trace_pending",
                correlation_id="corr_pending",
                source_id=source_id,
                adapter_name=adapter_name,
                handling_strategy=handling_strategy,
                error_code=error_code,
                retry_count=0,
                source_used_id=source_used_id,
                fallback_source_id=fallback_source_id,
                fallback_reason=fallback_reason,
                fallback_used=fallback_used,
                failure_class=failure_class,
                message=message,
                final_handling_strategy=handling_strategy,
                impacted_plan_types=impacted_plan_types,
                user_visible_message=user_visible_message,
                occurred_at=now_timepoint(),
            )
        )

def _nearby_station(place: str, mode: TransportMode, side: str) -> str:
    return nearby_transit_stop(place, mode, side)


def _place_point(place: str) -> GeoPoint | None:
    return resolve_location_point(place)


def _place_city(place: str) -> str | None:
    return resolve_location_city(place)


def _real_route_estimate(origin: str, destination: str, mode: TransportMode, collector: PlanningIssueCollector | None = None):
    origin_point = _place_point(origin)
    destination_point = _place_point(destination)
    if not origin_point or not destination_point:
        if collector:
            collector.add_missing("map_route")
            collector.add_warning("地图路线坐标不完整，相关接驳段使用规则估算并标记为降级。")
            collector.add_source_failure(
                source_id="map_route",
                adapter_name="MapRouteProvider",
                failure_class=SourceFailureClass.FALLBACK_AVAILABLE_FAILURE,
                handling_strategy=SourceFailureHandlingStrategy.FALLBACK,
                error_code="MAP_COORDINATES_MISSING",
                message=f"missing coordinates for real route estimate: {origin} -> {destination}",
                user_visible_message="地图路线坐标不完整，已使用规则估算接驳耗时和费用。",
                impacted_plan_types=[PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL, PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT, PlanType.FLIGHT_RAIL_MIXED],
                source_used_id=INTERNAL_SOURCE.source_id,
                fallback_source_id=INTERNAL_SOURCE.source_id,
                fallback_reason="missing coordinates for map route estimate",
                fallback_used=True,
            )
            return None
        raise ValueError(f"missing coordinates for real route estimate: {origin} -> {destination}")
    result = estimate_route_with_enabled_provider_result(
        MapRouteRequest(
            origin=origin_point,
            destination=destination_point,
            mode=mode,
            origin_city=_place_city(origin),
            destination_city=_place_city(destination),
        )
    )
    if result.estimate is None:
        if collector:
            source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "map_route"
            collector.add_missing("map_route")
            collector.add_warning("地图路线 Provider 不可用，相关接驳段使用规则估算并标记为降级。")
            collector.add_source_failure(
                source_id=source_id,
                adapter_name="MapRouteProvider",
                failure_class=SourceFailureClass.FALLBACK_AVAILABLE_FAILURE,
                handling_strategy=SourceFailureHandlingStrategy.FALLBACK,
                error_code="MAP_ROUTE_UNAVAILABLE",
                message=result.failure_message or f"real map route provider unavailable for {mode}: {origin} -> {destination}",
                user_visible_message="地图路线 Provider 暂不可用，已使用规则估算接驳耗时和费用。",
                impacted_plan_types=[PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL, PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT, PlanType.FLIGHT_RAIL_MIXED],
                source_used_id=INTERNAL_SOURCE.source_id,
                fallback_source_id=INTERNAL_SOURCE.source_id,
                fallback_reason=result.failure_message or "map provider returned no route estimate",
                fallback_used=True,
            )
            return None
        raise ValueError(f"real map route provider unavailable for {mode}: {origin} -> {destination}")
    if collector and result.fallback_used:
        collector.add_source_failure(
            source_id=result.attempted_source_ids[0],
            adapter_name="MapRouteProvider",
            failure_class=SourceFailureClass.FALLBACK_AVAILABLE_FAILURE,
            handling_strategy=SourceFailureHandlingStrategy.FALLBACK,
            error_code="MAP_ROUTE_FALLBACK_USED",
            message=result.fallback_reason or "map route fallback provider used",
            user_visible_message="首选地图 Provider 不可用，已使用备用地图数据源估算接驳。",
            impacted_plan_types=[PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL, PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT, PlanType.FLIGHT_RAIL_MIXED],
            source_used_id=result.fallback_source_id,
            fallback_source_id=result.fallback_source_id,
            fallback_reason=result.fallback_reason,
            fallback_used=True,
        )
    return result.estimate


def _transfer_options(origin: str, destination: str, minutes: int, cost_minor: int, collector: PlanningIssueCollector | None = None) -> list[LocalTransferOption]:
    subway_origin = _nearby_station(origin, TransportMode.SUBWAY, "origin")
    subway_destination = _nearby_station(destination, TransportMode.SUBWAY, "destination")
    bus_origin = _nearby_station(origin, TransportMode.BUS, "origin")
    bus_destination = _nearby_station(destination, TransportMode.BUS, "destination")
    taxi_estimate = _real_route_estimate(origin, destination, TransportMode.TAXI, collector)
    subway_estimate = _real_route_estimate(origin, destination, TransportMode.SUBWAY, collector)
    bus_estimate = _real_route_estimate(origin, destination, TransportMode.BUS, collector)
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
            ride_instruction=f"按 {taxi_estimate.summary} 估算行驶。" if taxi_estimate else "地图 Provider 暂不可用，本段按规则估算行驶时间和费用。",
            egress_instruction=f"在 {destination} 下车。",
            walking_distance_meters=120,
            data_source=taxi_estimate.data_source if taxi_estimate else INTERNAL_SOURCE,
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
            ride_instruction=f"按 {subway_estimate.summary} 前往 {subway_destination}。" if subway_estimate else f"地图 Provider 暂不可用，本段按规则估算乘坐地铁至 {subway_destination}。",
            egress_instruction=f"从 {subway_destination} 步行/短驳至 {destination}。",
            walking_distance_meters=780,
            data_source=subway_estimate.data_source if subway_estimate else INTERNAL_SOURCE,
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
            ride_instruction=f"按 {bus_estimate.summary} 前往 {bus_destination}。" if bus_estimate else f"地图 Provider 暂不可用，本段按规则估算乘坐公交至 {bus_destination}。",
            egress_instruction=f"从 {bus_destination} 步行/短驳至 {destination}。",
            walking_distance_meters=980,
            data_source=bus_estimate.data_source if bus_estimate else INTERNAL_SOURCE,
        ),
    ]


def _taxi(segment_id: str, origin: str, destination: str, minutes: int, cost_minor: int, option_id: str = "transfer_taxi", collector: PlanningIssueCollector | None = None) -> LocalTransferSegment:
    return build_local_transfer_segment(
        segment_id=segment_id,
        origin=origin,
        destination=destination,
        default_minutes=minutes,
        default_cost_minor=cost_minor,
        selected_option_id=option_id,
        route_estimator=estimate_route_with_enabled_provider_result,
        issue_sink=collector,
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
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "rail_12306_public_query"
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


def _rail_segment_from_offer(segment_id: str, offer: RailOffer) -> RailSegment:
    selected = next((seat for seat in offer.seat_options if seat.availability != "NO_TICKET"), offer.seat_options[0])
    return RailSegment(
        segment_id=segment_id,
        train_number=offer.train_number,
        origin_station=offer.origin_station,
        destination_station=offer.destination_station,
        departure_time=_timepoint_from_datetime(offer.departure_at, _tp(offer.departure_at.date(), offer.departure_at.hour, offer.departure_at.minute)),
        arrival_time=_timepoint_from_datetime(offer.arrival_at, _tp(offer.arrival_at.date(), offer.arrival_at.hour, offer.arrival_at.minute)),
        duration_minutes=offer.duration_minutes,
        stop_sequence=offer.stop_sequence,
        seat_options=offer.seat_options,
        selected_seat_option_id=selected.option_id,
        data_source=offer.data_source,
    )


def _cabin_options_from_offer(offer: FlightOffer) -> list[CabinOption]:
    if not offer.cabin_options:
        raise ValueError(f"flight offer {offer.offer_id} has no provider cabin options")
    return [
        CabinOption(
            option_id=cabin.option_id,
            cabin_type=cabin.cabin_type,
            price=cabin.price,
            availability=cabin.availability,
            source_option_version=cabin.source_option_version,
            data_source=offer.data_source,
        )
        for cabin in offer.cabin_options
        if cabin.availability in {"AVAILABLE", "LIMITED"}
    ]


def _selected_cabin_option_id(offer: FlightOffer) -> str:
    cabins = _cabin_options_from_offer(offer)
    if not cabins:
        raise ValueError(f"flight offer {offer.offer_id} has no available provider cabin options")
    return min(cabins, key=lambda cabin: cabin.price.amount_minor).option_id


def _flight(segment_id: str, flight: str, origin: str, destination: str, day, dep_h: int, dep_m: int, arr_h: int, arr_m: int, base_minor: int, previous_risk: bool = True) -> FlightSegment:
    codes = _flight_search_codes(flight, origin, destination)
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
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "airline_public_query"
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
        cabin_options=_cabin_options_from_offer(offer),
        selected_cabin_option_id=_selected_cabin_option_id(offer),
        previous_flight_risk_available=previous_risk,
        data_source=offer.data_source,
    )


def _real_direct_flight_segment(segment_id: str, flight: str, origin: str, destination: str, day, dep_h: int, dep_m: int, arr_h: int, arr_m: int, base_minor: int) -> FlightSegment:
    codes = _flight_search_codes(flight, origin, destination)
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
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "airline_public_query"
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
        cabin_options=_cabin_options_from_offer(offer),
        selected_cabin_option_id=_selected_cabin_option_id(offer),
        previous_flight_risk_available=True,
        data_source=offer.data_source,
    )


AIRPORT_IATA_CODES = {
    "上海虹桥机场": "SHA",
    "上海浦东机场": "PVG",
    "青岛胶东机场": "TAO",
    "北京首都机场": "PEK",
    "北京大兴机场": "PKX",
    "广州白云机场": "CAN",
    "济南遥墙机场": "TNA",
    "武汉天河机场": "WUH",
    "长沙黄花机场": "CSX",
}


def _flight_search_codes(flight: str, origin_airport: str | None = None, destination_airport: str | None = None) -> tuple[str, str] | None:
    if origin_airport in AIRPORT_IATA_CODES and destination_airport in AIRPORT_IATA_CODES:
        return (AIRPORT_IATA_CODES[origin_airport], AIRPORT_IATA_CODES[destination_airport])
    if flight.startswith("MU"):
        return ("SHA", "TAO")
    if flight.startswith("CZ"):
        return ("PEK", "CAN")
    if flight.startswith("SC"):
        return ("TNA", "TAO")
    return None


def _timepoint_from_datetime(value: datetime | None, fallback: TimePoint) -> TimePoint:
    if value is None:
        return fallback
    return TimePoint(datetime=_as_shanghai_datetime(value), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _timepoint_exact(value: datetime) -> TimePoint:
    return TimePoint(datetime=_as_shanghai_datetime(value), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def _pre_departure_buffer_minutes(segment) -> int:
    if isinstance(segment, FlightSegment):
        return 90
    if isinstance(segment, RailSegment):
        return 20
    return 0


def _post_arrival_buffer_minutes(segment) -> int:
    if isinstance(segment, FlightSegment):
        return 35
    if isinstance(segment, RailSegment):
        return 10
    return 0


def _first_timepoint(segments, attr: str) -> TimePoint | None:
    for segment in segments:
        value = getattr(segment, attr, None)
        if value:
            return value
    return None


def _last_timepoint(segments, attr: str) -> TimePoint | None:
    values = [getattr(segment, attr, None) for segment in segments if getattr(segment, attr, None)]
    return values[-1] if values else None


def _apply_door_to_door_schedule(segments) -> None:
    main_indexes = [index for index, segment in enumerate(segments) if isinstance(segment, (RailSegment, FlightSegment))]
    for index, segment in enumerate(segments):
        if not isinstance(segment, LocalTransferSegment):
            continue
        previous_index = next((main_index for main_index in reversed(main_indexes) if main_index < index), None)
        next_index = next((main_index for main_index in main_indexes if main_index > index), None)
        previous_main = segments[previous_index] if previous_index is not None else None
        next_main = segments[next_index] if next_index is not None else None
        transfer_duration = timedelta(minutes=segment.duration_minutes)

        departure_at: datetime | None = None
        arrival_at: datetime | None = None
        if previous_main is None and next_main is not None:
            next_departure = _segment_departure_at(next_main)
            if next_departure is not None:
                arrival_at = next_departure - timedelta(minutes=_pre_departure_buffer_minutes(next_main))
                departure_at = arrival_at - transfer_duration
        elif previous_main is not None and next_main is None:
            previous_arrival = _segment_arrival_at(previous_main)
            if previous_arrival is not None:
                departure_at = previous_arrival + timedelta(minutes=_post_arrival_buffer_minutes(previous_main))
                arrival_at = departure_at + transfer_duration
        elif previous_main is not None and next_main is not None:
            previous_arrival = _segment_arrival_at(previous_main)
            next_departure = _segment_departure_at(next_main)
            if previous_arrival is not None and next_departure is not None:
                earliest_departure = previous_arrival + timedelta(minutes=_post_arrival_buffer_minutes(previous_main))
                latest_arrival = next_departure - timedelta(minutes=_pre_departure_buffer_minutes(next_main))
                departure_at = earliest_departure
                arrival_at = departure_at + transfer_duration
                if arrival_at > latest_arrival:
                    arrival_at = latest_arrival
                    departure_at = arrival_at - transfer_duration

        if departure_at is not None and arrival_at is not None:
            segment.departure_time = _timepoint_exact(departure_at)
            segment.arrival_time = _timepoint_exact(arrival_at)


def _refresh_plan_schedule(plan: TravelPlan) -> None:
    _apply_door_to_door_schedule(plan.segments)
    plan.departure_time = _first_timepoint(plan.segments, "departure_time")
    plan.arrival_time = _last_timepoint(plan.segments, "arrival_time")
    if plan.departure_time and plan.arrival_time:
        plan.total_duration_minutes = max(0, int((plan.arrival_time.datetime - plan.departure_time.datetime).total_seconds() // 60))
    else:
        plan.total_duration_minutes = sum(segment.duration_minutes for segment in plan.segments)


def _real_flight_block_failure(travel_request: TravelRequest, source_id: str, message: str) -> SourceFailure:
    return SourceFailure(
        failure_id=f"fail_{uuid4().hex[:8]}",
        request_id=travel_request.request_id,
        trace_id="trace_pending",
        correlation_id="corr_pending",
        source_id=source_id,
        adapter_name="FlightPlanningProvider",
        handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
        error_code="FLIGHT_CORE_FACT_UNAVAILABLE",
        retry_count=0,
        source_used_id=None,
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
        message=message,
        final_handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
        impacted_plan_types=[PlanType.DIRECT_FLIGHT],
        user_visible_message="真实航班搜索不可用，直飞航班方案已阻断；系统不会用测试数据冒充真实结果。",
        occurred_at=now_timepoint(),
    )


def _plan(plan_id: str, name: str, plan_type: PlanType, segments, comfort: float, risk: RiskLevel, risk_title: str, risk_message: str, ticket: TicketEnhancement | None = None, eligibility: RecommendationEligibility = RecommendationEligibility.ELIGIBLE, can_llm: bool = True, block_code: str | None = None, block_message: str | None = None) -> TravelPlan:
    _apply_door_to_door_schedule(segments)
    cost = calculate_cost_breakdown(segments, ticket)
    data_sources = list({item.source_id: item for item in [INTERNAL_SOURCE, *[segment.data_source for segment in segments], *[ci.data_source for ci in cost.items]]}.values())
    departure_time = _first_timepoint(segments, "departure_time")
    arrival_time = _last_timepoint(segments, "arrival_time")
    total_duration = sum(segment.duration_minutes for segment in segments)
    if departure_time and arrival_time:
        total_duration = max(0, int((arrival_time.datetime - departure_time.datetime).total_seconds() // 60))
    return TravelPlan(
        plan_id=plan_id,
        plan_name=name,
        plan_type=plan_type,
        plan_lifecycle_status=PlanLifecycleStatus.GENERATED,
        recommendation_eligibility=eligibility,
        can_be_selected_by_llm=can_llm,
        block_reason_code=block_code,
        block_reason_message=block_message,
        segments=segments,
        ticket_enhancement=ticket,
        total_duration_minutes=total_duration,
        departure_time=departure_time,
        arrival_time=arrival_time,
        cost_breakdown=cost,
        comfort_score=build_comfort_score(comfort, name, risk),
        risk_assessment=build_risk_assessment(risk, risk_title, risk_message, INTERNAL_SOURCE),
        data_quality=build_data_quality(risk, risk_message),
        data_sources=data_sources,
        booking_redirects=[],
    )


def _ticket(spec: TicketEnhancementSpec) -> TicketEnhancement:
    return TicketEnhancement(
        enhancement_id=spec.enhancement_id,
        grade=spec.grade,
        actual_origin=spec.actual_origin,
        actual_destination=spec.actual_destination,
        ticket_origin=spec.ticket_origin,
        ticket_destination=spec.ticket_destination,
        ticket_covers_actual_route=spec.ticket_covers_actual_route,
        requires_onboard_supplement=spec.requires_onboard_supplement,
        unused_distance_ratio=spec.unused_distance_ratio,
        extra_cost=money(spec.extra_cost_minor),
        extra_cost_ratio=spec.extra_cost_ratio,
        risk_level=spec.risk_level,
        recommendation_message=spec.recommendation_message,
        validation_source="authorized_rail_partner_station_sequence",
        validation_rule_version="ticket_enhancement_v1",
        data_source=RAIL_SOURCE,
    )


def _rail_transfer_segment_ids(plan_id: str) -> tuple[str, str]:
    stable_ids = {
        "plan_rail_direct_shqd": ("seg_origin_station", "seg_station_dest"),
        "plan_rail_direct_bg": ("seg_origin_station", "seg_station_dest"),
        "plan_rail_transfer_shqd": ("seg_origin_station_transfer", "seg_station_dest_transfer"),
        "plan_rail_transfer_bg": ("seg_origin_station_transfer", "seg_station_dest_transfer"),
        "plan_ticket_s_shqd": ("seg_origin_station_ticket_s", "seg_station_dest_ticket_s"),
        "plan_ticket_a_shqd": ("seg_origin_station_ticket_a", "seg_station_dest_ticket_a"),
        "plan_buy_short_shqd": ("seg_origin_station_buy_short", "seg_station_dest_buy_short"),
        "plan_blocked_shqd": ("seg_origin_station_blocked", "seg_station_dest_blocked"),
    }
    return stable_ids.get(plan_id, (f"seg_origin_station_{plan_id}", f"seg_station_dest_{plan_id}"))


def _rail_plan_from_spec(
    spec: RailPlanSpec,
    *,
    day,
    city_origin: str,
    city_destination: str,
    start_station: str,
    end_station: str,
    taxi,
) -> TravelPlan:
    origin_segment_id, destination_segment_id = _rail_transfer_segment_ids(spec.plan_id)
    rail_segments = [
        _rail(
            leg.segment_id,
            leg.train_number,
            leg.origin_station,
            leg.destination_station,
            day,
            leg.departure_hour,
            leg.departure_minute,
            leg.arrival_hour,
            leg.arrival_minute,
            leg.base_fare_minor,
            leg.stop_sequence,
        )
        for leg in spec.legs
    ]
    segments = [
        taxi(origin_segment_id, city_origin, f"{start_station}站", 38, 7800),
        *rail_segments,
        taxi(destination_segment_id, f"{end_station}站", city_destination, 32, 6200),
    ]
    ticket = _ticket(spec.ticket_enhancement) if spec.ticket_enhancement else None
    return _plan(
        spec.plan_id,
        spec.plan_name,
        spec.plan_type,
        segments,
        spec.comfort_score,
        spec.risk_level,
        spec.risk_title,
        spec.risk_message,
        ticket=ticket,
        eligibility=spec.eligibility,
        can_llm=spec.can_be_selected_by_llm,
        block_code=spec.block_reason_code,
        block_message=spec.block_reason_message,
    )


def _dynamic_station_names(route_nodes, city: str, limit: int = 2) -> list[str]:
    names: list[str] = []
    for candidate in route_nodes.station_candidates:
        if candidate.city_name == city and candidate.station_name not in names:
            names.append(candidate.station_name)
    return names[:limit]


def _dynamic_airport_candidates(route_nodes, city: str, limit: int = 2) -> list[AirportCandidate]:
    candidates: list[AirportCandidate] = []
    seen: set[str] = set()
    for candidate in [*route_nodes.airport_candidates, *airport_candidates_for_city(city, limit=limit)]:
        key = candidate.airport_id or candidate.airport_name
        if candidate.city_name == city and key not in seen and airport_iata_for_candidate(candidate):
            seen.add(key)
            candidates.append(candidate)
    return candidates[:limit]


def _segment_departure_at(segment) -> datetime | None:
    value = getattr(segment, "departure_time", None)
    return value.datetime if value else None


def _segment_arrival_at(segment) -> datetime | None:
    value = getattr(segment, "arrival_time", None)
    return value.datetime if value else None


def _has_connection(previous_segment, next_segment, min_minutes: int) -> bool:
    previous_arrival = _segment_arrival_at(previous_segment)
    next_departure = _segment_departure_at(next_segment)
    if previous_arrival is None or next_departure is None:
        return False
    return next_departure >= previous_arrival + timedelta(minutes=min_minutes)


def _flight_segments_from_offer(
    *,
    segment_prefix: str,
    offer: FlightOffer,
    day,
    origin_airport_name: str,
    destination_airport_name: str,
) -> list[FlightSegment]:
    segments: list[FlightSegment] = []
    segment_count = max(1, len(offer.segments))
    for index, offer_segment in enumerate(offer.segments, start=1):
        fallback_dep = _tp(day, 9 + min(index, 8), 0)
        fallback_arr = TimePoint(datetime=fallback_dep.datetime + timedelta(minutes=120), timezone=fallback_dep.timezone, source_timezone=fallback_dep.source_timezone)
        dep = _timepoint_from_datetime(offer_segment.departure_at, fallback_dep)
        arr = _timepoint_from_datetime(offer_segment.arrival_at, fallback_arr)
        duration = max(0, int((arr.datetime - dep.datetime).total_seconds() // 60))
        origin_label = origin_airport_name if index == 1 else offer_segment.origin_iata
        destination_label = destination_airport_name if index == len(offer.segments) else offer_segment.destination_iata
        flight_number = f"{offer_segment.carrier_code}{offer_segment.flight_number}".strip() or f"{offer_segment.origin_iata}-{offer_segment.destination_iata}"
        segment_price = money(offer.total_price.amount_minor // segment_count + (offer.total_price.amount_minor % segment_count if index == 1 else 0))
        cabin_options = _cabin_options_from_offer(offer)
        selected_cabin_id = _selected_cabin_option_id(offer)
        segments.append(
            FlightSegment(
                segment_id=f"{segment_prefix}_{index}",
                flight_number=flight_number,
                origin_airport=origin_label,
                destination_airport=destination_label,
                departure_time=dep,
                arrival_time=arr,
                duration_minutes=duration,
                cabin_options=[
                    cabin.model_copy(update={"price": segment_price}) if segment_count > 1 else cabin
                    for cabin in cabin_options
                ],
                selected_cabin_option_id=selected_cabin_id,
                previous_flight_risk_available=len(offer.segments) == 1,
                data_source=offer.data_source,
            )
        )
    return segments


def _flight_provider_error_code(message: str | None) -> str:
    value = message or ""
    lowered = value.lower()
    if "no enabled" in lowered or "disabled" in lowered:
        return "FLIGHT_PROVIDER_DISABLED"
    if any(marker in lowered for marker in ("unauthorized", "credential", "key", "forbidden", "401", "403")):
        return "FLIGHT_PROVIDER_UNAUTHORIZED"
    if any(marker in lowered for marker in ("timeout", "timed out")):
        return "FLIGHT_PROVIDER_TIMEOUT"
    if "empty response" in lowered or "no offers" in lowered:
        return "FLIGHT_PROVIDER_EMPTY"
    if value:
        return "FLIGHT_PROVIDER_ERROR"
    return "FLIGHT_PROVIDER_EMPTY"


def _flight_provider_user_message(error_code: str) -> str:
    if error_code == "FLIGHT_PROVIDER_DISABLED":
        return "Flight provider is not enabled or configured; flight plans are blocked."
    if error_code == "FLIGHT_PROVIDER_UNAUTHORIZED":
        return "Flight provider credentials or authorization are unavailable; flight plans are blocked."
    if error_code == "FLIGHT_PROVIDER_TIMEOUT":
        return "Flight provider timed out; flight plans are blocked for this run."
    if error_code == "FLIGHT_PROVIDER_ERROR":
        return "Flight provider search failed; flight plans are blocked for this run."
    return "Flight provider returned no verifiable offers for the searched airport pairs."


def _rail_provider_error_code(message: str) -> str:
    if any(marker in message for marker in ("超过每日", "次数", "频率", "限制", "quota", "rate limit", "limit")):
        return "RAIL_PROVIDER_RATE_LIMITED"
    if any(marker in message for marker in ("station code missing", "站点编码", "电报码")):
        return "RAIL_PROVIDER_STATION_CODE_MISSING"
    if "no priced available seats" in message or "缺价" in message or "票价" in message:
        return "RAIL_PROVIDER_MISSING_PRICE"
    if message and "empty response" in message and not any(marker in message for marker in ("failed", "error", "Exception", "异常", "失败")):
        return "RAIL_PROVIDER_EMPTY"
    if message:
        return "RAIL_PROVIDER_ERROR"
    return "RAIL_PROVIDER_EMPTY"


def _rail_provider_user_message(error_code: str) -> str:
    if error_code == "RAIL_PROVIDER_RATE_LIMITED":
        return "12306 公开查询触发调用频率或访问限制，暂时无法验证真实车次、票价和有票席别。"
    if error_code == "RAIL_PROVIDER_STATION_CODE_MISSING":
        return "未能从 12306 站名目录匹配完整站点电报码，铁路方案已阻断。"
    if error_code == "RAIL_PROVIDER_MISSING_PRICE":
        return "12306 公开查询未返回可同时验证有票和票价的席别，铁路方案已阻断。"
    if error_code == "RAIL_PROVIDER_ERROR":
        return "12306 公开查询失败，暂时无法验证真实车次、票价和有票席别。"
    return "12306 公开查询暂未返回可验证的有票直达车次，已阻断铁路直达方案。"


def _record_rail_provider_block(
    collector: PlanningIssueCollector,
    *,
    failure_messages: list[str],
    missing_component: str,
    impacted_plan_types: list[PlanType],
) -> None:
    if not failure_messages:
        return
    failure_message = "; ".join(failure_messages)
    error_code = _rail_provider_error_code(failure_message)
    user_visible_message = _rail_provider_user_message(error_code)
    logger.warning(
        "rail_planner_block missing_component=%s error_code=%s impacted_plan_types=%s failure_message=%s",
        missing_component,
        error_code,
        ",".join(plan_type.value for plan_type in impacted_plan_types),
        failure_message,
    )
    collector.add_missing(missing_component)
    collector.add_warning(user_visible_message)
    collector.add_source_failure(
        source_id="rail_12306_public_query",
        adapter_name="RailPlanningProvider",
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
        error_code=error_code,
        message=failure_message,
        user_visible_message=user_visible_message,
        impacted_plan_types=impacted_plan_types,
        source_used_id=None,
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
    )


def _direct_rail_block_message(collector: PlanningIssueCollector) -> str:
    for failure in collector.failures:
        if failure.source_id == "rail_12306_public_query" and failure.error_code != "RAIL_PROVIDER_EMPTY":
            return failure.user_visible_message
    return "12306 公开查询暂未返回可验证的有票直达车次，动态直达铁路方案已阻断。"


def _build_dynamic_direct_rail_plans(
    *,
    travel_request: TravelRequest,
    route_nodes,
    day,
    origin_text: str,
    destination_text: str,
    origin_city: str,
    destination_city: str,
    taxi,
    collector: PlanningIssueCollector,
    max_station_pairs: int = 4,
    max_plans: int = 4,
) -> list[TravelPlan]:
    origin_stations = _dynamic_station_names(route_nodes, origin_city)
    destination_stations = _dynamic_station_names(route_nodes, destination_city)
    logger.info(
        "rail_direct_planner_start request_id=%s origin_city=%s destination_city=%s origin_station_count=%s destination_station_count=%s",
        travel_request.request_id,
        origin_city,
        destination_city,
        len(origin_stations),
        len(destination_stations),
    )
    if not origin_stations or not destination_stations:
        logger.warning(
            "rail_direct_planner_missing_station_candidates request_id=%s origin_stations=%s destination_stations=%s",
            travel_request.request_id,
            origin_stations,
            destination_stations,
        )
        collector.add_missing("rail_station_candidates")
        collector.add_warning("未能生成完整的铁路站点候选，动态铁路方案已阻断。")
        return []

    plans: list[TravelPlan] = []
    failure_messages: list[str] = []
    failure_source_ids: list[str] = []
    station_pairs = [(origin_station, destination_station) for origin_station in origin_stations for destination_station in destination_stations][:max_station_pairs]
    logger.info("rail_direct_station_pairs request_id=%s pair_count=%s station_pairs=%s", travel_request.request_id, len(station_pairs), station_pairs)
    for pair_index, (origin_station, destination_station) in enumerate(station_pairs, start=1):
        logger.info(
            "rail_direct_provider_query request_id=%s pair_index=%s origin_station=%s destination_station=%s",
            travel_request.request_id,
            pair_index,
            origin_station,
            destination_station,
        )
        result = search_rail_offers_with_enabled_provider_result(
            RailSearchRequest(
                train_number="",
                origin_station=origin_station,
                destination_station=destination_station,
                departure_date=day,
            )
        )
        if not result.offers:
            failure_message = f"{origin_station}->{destination_station}: {result.failure_message or 'no rail offers returned'}"
            failure_messages.append(failure_message)
            logger.info(
                "rail_direct_provider_empty request_id=%s pair_index=%s origin_station=%s destination_station=%s failure_message=%s",
                travel_request.request_id,
                pair_index,
                origin_station,
                destination_station,
                failure_message,
            )
            if _rail_provider_error_code(failure_message) == "RAIL_PROVIDER_RATE_LIMITED":
                logger.warning("rail_direct_provider_rate_limited request_id=%s pair_index=%s", travel_request.request_id, pair_index)
                break
            continue
        logger.info(
            "rail_direct_provider_result request_id=%s pair_index=%s offer_count=%s",
            travel_request.request_id,
            pair_index,
            len(result.offers),
        )
        for offer_index, offer in enumerate(result.offers[: max(1, max_plans - len(plans))], start=1):
            plan_index = len(plans) + 1
            rail_segment = _rail_segment_from_offer(f"seg_rail_dynamic_direct_{plan_index}", offer)
            segments = [
                taxi(f"seg_origin_station_dynamic_{plan_index}", origin_text, f"{offer.origin_station}站", 38, 7800),
                rail_segment,
                taxi(f"seg_station_dest_dynamic_{plan_index}", f"{offer.destination_station}站", destination_text, 32, 6200),
            ]
            plans.append(
                _plan(
                    f"plan_rail_direct_dynamic_{plan_index}",
                    f"动态高铁直达 {offer.train_number}",
                    PlanType.DIRECT_RAIL,
                    segments,
                    8.0 if pair_index == 1 and offer_index == 1 else 7.6,
                    RiskLevel.LOW,
                    "12306 公开查询返回",
                    "车次、时间、票价和席别来自 12306 公开匿名查询；接驳段由地图 Provider 或明确降级估算生成。",
                )
            )
            logger.info(
                "rail_direct_plan_created request_id=%s plan_id=%s train_number=%s selected_seat_count=%s",
                travel_request.request_id,
                f"plan_rail_direct_dynamic_{plan_index}",
                offer.train_number,
                len(offer.seat_options),
            )
            if len(plans) >= max_plans:
                logger.info("rail_direct_planner_complete request_id=%s plan_count=%s reason=max_plans", travel_request.request_id, len(plans))
                return plans

    if not plans:
        _record_rail_provider_block(
            collector,
            failure_messages=failure_messages,
            missing_component="rail_core_fact",
            impacted_plan_types=[PlanType.DIRECT_RAIL],
        )
    logger.info("rail_direct_planner_complete request_id=%s plan_count=%s", travel_request.request_id, len(plans))
    return plans


def _build_dynamic_flight_plans(
    *,
    travel_request: TravelRequest,
    route_nodes,
    day,
    origin_text: str,
    destination_text: str,
    origin_city: str,
    destination_city: str,
    taxi,
    collector: PlanningIssueCollector,
    max_airport_pairs: int = 2,
    max_plans: int = 2,
) -> list[TravelPlan]:
    origin_airports = _dynamic_airport_candidates(route_nodes, origin_city)
    destination_airports = _dynamic_airport_candidates(route_nodes, destination_city)
    if not origin_airports or not destination_airports:
        collector.add_missing("flight_airport_candidates")
        return []

    plans: list[TravelPlan] = []
    failure_messages: list[str] = []
    failure_source_ids: list[str] = []
    airport_pairs = [(origin_airport, destination_airport) for origin_airport in origin_airports for destination_airport in destination_airports][:max_airport_pairs]
    for pair_index, (origin_airport, destination_airport) in enumerate(airport_pairs, start=1):
        origin_iata = airport_iata_for_candidate(origin_airport)
        destination_iata = airport_iata_for_candidate(destination_airport)
        if not origin_iata or not destination_iata:
            continue
        result = search_flight_offers_with_enabled_provider_result(
            FlightSearchRequest(
                origin_iata=origin_iata,
                destination_iata=destination_iata,
                departure_date=day,
                adults=1,
                currency_code="CNY",
                max_results=max_plans,
                non_stop=None,
            )
        )
        if not result.offers:
            failure_messages.append(f"{origin_iata}->{destination_iata}: {result.failure_message or 'no flight offers returned'}")
            failure_source_ids.extend(result.attempted_source_ids)
            continue
        for offer_index, offer in enumerate(result.offers[: max(1, max_plans - len(plans))], start=1):
            flight_segments = _flight_segments_from_offer(
                segment_prefix=f"seg_flight_dynamic_{len(plans) + 1}",
                offer=offer,
                day=day,
                origin_airport_name=origin_airport.airport_name,
                destination_airport_name=destination_airport.airport_name,
            )
            if not flight_segments:
                continue
            plan_index = len(plans) + 1
            is_transfer = len(flight_segments) > 1
            segments = [
                taxi(f"seg_origin_airport_dynamic_{plan_index}", origin_text, origin_airport.airport_name, 52, 11800),
                *flight_segments,
                taxi(f"seg_airport_dest_dynamic_{plan_index}", destination_airport.airport_name, destination_text, 54, 13600),
            ]
            plans.append(
                _plan(
                    f"plan_flight_dynamic_{plan_index}",
                    f"Dynamic flight {flight_segments[0].flight_number}",
                    PlanType.TRANSFER_FLIGHT if is_transfer else PlanType.DIRECT_FLIGHT,
                    segments,
                    7.8 if pair_index == 1 and offer_index == 1 else 7.4,
                    RiskLevel.MEDIUM if is_transfer else RiskLevel.LOW,
                    "Verified flight provider offer",
                    "Flight times and fare come from the enabled flight provider; local transfers are map-backed or explicitly estimated.",
                )
            )
            if len(plans) >= max_plans:
                return plans

    if not plans and failure_messages:
        failure_message = "; ".join(failure_messages)
        error_code = _flight_provider_error_code(failure_message)
        user_visible_message = _flight_provider_user_message(error_code)
        collector.add_missing("flight_core_fact")
        collector.add_warning(user_visible_message)
        collector.add_source_failure(
            source_id=failure_source_ids[-1] if failure_source_ids else "airline_public_query",
            adapter_name="FlightPlanningProvider",
            failure_class=SourceFailureClass.CORE_FACT_FAILURE,
            handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
            error_code=error_code,
            message=failure_message,
            user_visible_message=user_visible_message,
            impacted_plan_types=[PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT],
            source_used_id=None,
            fallback_source_id=None,
            fallback_reason=None,
            fallback_used=False,
        )
    return plans


def _build_dynamic_transfer_rail_plans(
    *,
    travel_request: TravelRequest,
    route_nodes,
    day,
    origin_text: str,
    destination_text: str,
    origin_city: str,
    destination_city: str,
    taxi,
    collector: PlanningIssueCollector,
    max_hubs: int = 6,
    max_plans: int = 3,
) -> list[TravelPlan]:
    origin_stations = _dynamic_station_names(route_nodes, origin_city, limit=2)
    destination_stations = _dynamic_station_names(route_nodes, destination_city, limit=2)
    transfer_stations = transfer_station_candidates_between(origin_city, destination_city, limit=max_hubs)
    logger.info(
        "rail_transfer_planner_start request_id=%s origin_station_count=%s destination_station_count=%s transfer_station_count=%s",
        travel_request.request_id,
        len(origin_stations),
        len(destination_stations),
        len(transfer_stations),
    )
    if not origin_stations or not destination_stations or not transfer_stations:
        logger.warning(
            "rail_transfer_planner_missing_candidates request_id=%s origin_stations=%s destination_stations=%s transfer_station_count=%s",
            travel_request.request_id,
            origin_stations,
            destination_stations,
            len(transfer_stations),
        )
        collector.add_missing("rail_transfer_candidates")
        return []

    plans: list[TravelPlan] = []
    failure_messages: list[str] = []
    rail_rate_limited = False
    for origin_station in origin_stations:
        if rail_rate_limited:
            break
        for transfer_station in transfer_stations:
            if transfer_station.station_name == origin_station:
                continue
            logger.info(
                "rail_transfer_first_leg_query request_id=%s origin_station=%s transfer_station=%s",
                travel_request.request_id,
                origin_station,
                transfer_station.station_name,
            )
            first_result = search_rail_offers_with_enabled_provider_result(
                RailSearchRequest(
                    train_number="",
                    origin_station=origin_station,
                    destination_station=transfer_station.station_name,
                    departure_date=day,
                )
            )
            if not first_result.offers:
                failure_messages.append(f"{origin_station}->{transfer_station.station_name}: {first_result.failure_message or 'no rail offers returned'}")
                logger.info(
                    "rail_transfer_first_leg_empty request_id=%s origin_station=%s transfer_station=%s failure_message=%s",
                    travel_request.request_id,
                    origin_station,
                    transfer_station.station_name,
                    failure_messages[-1],
                )
                if _rail_provider_error_code(failure_messages[-1]) == "RAIL_PROVIDER_RATE_LIMITED":
                    rail_rate_limited = True
                    break
                continue
            for destination_station in destination_stations:
                if rail_rate_limited:
                    break
                if transfer_station.station_name == destination_station:
                    continue
                logger.info(
                    "rail_transfer_second_leg_query request_id=%s transfer_station=%s destination_station=%s",
                    travel_request.request_id,
                    transfer_station.station_name,
                    destination_station,
                )
                second_result = search_rail_offers_with_enabled_provider_result(
                    RailSearchRequest(
                        train_number="",
                        origin_station=transfer_station.station_name,
                        destination_station=destination_station,
                        departure_date=day,
                    )
                )
                if not second_result.offers:
                    failure_messages.append(f"{transfer_station.station_name}->{destination_station}: {second_result.failure_message or 'no rail offers returned'}")
                    logger.info(
                        "rail_transfer_second_leg_empty request_id=%s transfer_station=%s destination_station=%s failure_message=%s",
                        travel_request.request_id,
                        transfer_station.station_name,
                        destination_station,
                        failure_messages[-1],
                    )
                    if _rail_provider_error_code(failure_messages[-1]) == "RAIL_PROVIDER_RATE_LIMITED":
                        rail_rate_limited = True
                        break
                    continue
                for first_offer in first_result.offers[:2]:
                    first_segment = _rail_segment_from_offer(f"seg_rail_transfer_{len(plans) + 1}_1", first_offer)
                    for second_offer in second_result.offers[:2]:
                        second_segment = _rail_segment_from_offer(f"seg_rail_transfer_{len(plans) + 1}_2", second_offer)
                        if not _has_connection(first_segment, second_segment, 45):
                            continue
                        plan_index = len(plans) + 1
                        segments = [
                            taxi(f"seg_origin_station_transfer_dynamic_{plan_index}", origin_text, f"{first_offer.origin_station}", 38, 7800),
                            first_segment,
                            taxi(f"seg_transfer_station_dynamic_{plan_index}", f"{first_offer.destination_station}", f"{second_offer.origin_station}", 20, 0),
                            second_segment,
                            taxi(f"seg_station_dest_transfer_dynamic_{plan_index}", f"{second_offer.destination_station}", destination_text, 32, 6200),
                        ]
                        plans.append(
                            _plan(
                                f"plan_rail_transfer_dynamic_{plan_index}",
                                f"Dynamic rail transfer via {transfer_station.station_name}",
                                PlanType.TRANSFER_RAIL,
                                segments,
                                7.2,
                                RiskLevel.MEDIUM,
                                "Verified two-leg rail provider offers",
                                "Both rail legs come from the enabled rail provider and pass a minimum transfer-time check.",
                            )
                        )
                        logger.info(
                            "rail_transfer_plan_created request_id=%s plan_id=%s transfer_station=%s first_train=%s second_train=%s",
                            travel_request.request_id,
                            f"plan_rail_transfer_dynamic_{plan_index}",
                            transfer_station.station_name,
                            first_offer.train_number,
                            second_offer.train_number,
                        )
                        if len(plans) >= max_plans:
                            logger.info("rail_transfer_planner_complete request_id=%s plan_count=%s reason=max_plans", travel_request.request_id, len(plans))
                            return plans

    if not plans:
        _record_rail_provider_block(
            collector,
            failure_messages=failure_messages,
            missing_component="rail_transfer_core_fact",
            impacted_plan_types=[PlanType.TRANSFER_RAIL],
        )
    logger.info("rail_transfer_planner_complete request_id=%s plan_count=%s rail_rate_limited=%s", travel_request.request_id, len(plans), rail_rate_limited)
    return plans


def _build_dynamic_flight_rail_mixed_plans(
    *,
    travel_request: TravelRequest,
    route_nodes,
    day,
    origin_text: str,
    destination_text: str,
    origin_city: str,
    destination_city: str,
    taxi,
    collector: PlanningIssueCollector,
    max_hubs: int = 4,
    max_plans: int = 2,
) -> list[TravelPlan]:
    origin_stations = _dynamic_station_names(route_nodes, origin_city, limit=2)
    destination_stations = _dynamic_station_names(route_nodes, destination_city, limit=2)
    origin_airports = _dynamic_airport_candidates(route_nodes, origin_city, limit=2)
    destination_airports = _dynamic_airport_candidates(route_nodes, destination_city, limit=2)
    transfer_stations = transfer_station_candidates_between(origin_city, destination_city, limit=max_hubs)
    plans: list[TravelPlan] = []
    failure_messages: list[str] = []
    rail_rate_limited = False
    logger.info(
        "rail_mixed_planner_start request_id=%s origin_station_count=%s destination_station_count=%s origin_airport_count=%s destination_airport_count=%s transfer_station_count=%s",
        travel_request.request_id,
        len(origin_stations),
        len(destination_stations),
        len(origin_airports),
        len(destination_airports),
        len(transfer_stations),
    )

    for transfer_station in transfer_stations:
        if rail_rate_limited:
            break
        hub_airports = airport_candidates_for_city(transfer_station.city_name, limit=2)
        hub_airports = [airport for airport in hub_airports if airport_iata_for_candidate(airport)]
        if not hub_airports:
            continue

        for origin_airport in origin_airports:
            for destination_station in destination_stations:
                for hub_airport in hub_airports:
                    origin_iata = airport_iata_for_candidate(origin_airport)
                    hub_iata = airport_iata_for_candidate(hub_airport)
                    if not origin_iata or not hub_iata:
                        continue
                    flight_result = search_flight_offers_with_enabled_provider_result(
                        FlightSearchRequest(origin_iata=origin_iata, destination_iata=hub_iata, departure_date=day, adults=1, currency_code="CNY", max_results=2, non_stop=None)
                    )
                    rail_result = search_rail_offers_with_enabled_provider_result(
                        RailSearchRequest(train_number="", origin_station=transfer_station.station_name, destination_station=destination_station, departure_date=day)
                    )
                    if not flight_result.offers or not rail_result.offers:
                        failure_messages.append(f"flight-rail via {transfer_station.station_name}: flight={flight_result.failure_message or len(flight_result.offers)} rail={rail_result.failure_message or len(rail_result.offers)}")
                        logger.info(
                            "rail_mixed_flight_rail_empty request_id=%s transfer_station=%s destination_station=%s failure_message=%s",
                            travel_request.request_id,
                            transfer_station.station_name,
                            destination_station,
                            failure_messages[-1],
                        )
                        if _rail_provider_error_code(failure_messages[-1]) == "RAIL_PROVIDER_RATE_LIMITED":
                            rail_rate_limited = True
                            break
                        continue
                    flight_segments = _flight_segments_from_offer(
                        segment_prefix=f"seg_mixed_flight_first_{len(plans) + 1}",
                        offer=flight_result.offers[0],
                        day=day,
                        origin_airport_name=origin_airport.airport_name,
                        destination_airport_name=hub_airport.airport_name,
                    )
                    rail_segment = _rail_segment_from_offer(f"seg_mixed_rail_second_{len(plans) + 1}", rail_result.offers[0])
                    if flight_segments and _has_connection(flight_segments[-1], rail_segment, 90):
                        plan_index = len(plans) + 1
                        plans.append(
                            _plan(
                                f"plan_flight_rail_mixed_dynamic_{plan_index}",
                                f"Dynamic flight-rail via {transfer_station.city_name}",
                                PlanType.FLIGHT_RAIL_MIXED,
                                [
                                    taxi(f"seg_mixed_origin_airport_{plan_index}", origin_text, origin_airport.airport_name, 52, 11800),
                                    *flight_segments,
                                    taxi(f"seg_mixed_airport_station_{plan_index}", hub_airport.airport_name, transfer_station.station_name, 50, 9000),
                                    rail_segment,
                                    taxi(f"seg_mixed_station_dest_{plan_index}", rail_segment.destination_station, destination_text, 32, 6200),
                                ],
                                7.0,
                                RiskLevel.MEDIUM,
                                "Verified flight and rail provider offers",
                                "The flight and rail facts both come from enabled providers and pass a connection-time check.",
                            )
                        )
                        logger.info(
                            "rail_mixed_flight_rail_plan_created request_id=%s plan_id=%s transfer_city=%s rail_train=%s",
                            travel_request.request_id,
                            f"plan_flight_rail_mixed_dynamic_{plan_index}",
                            transfer_station.city_name,
                            rail_segment.train_number,
                        )
                        if len(plans) >= max_plans:
                            logger.info("rail_mixed_planner_complete request_id=%s plan_count=%s reason=max_plans", travel_request.request_id, len(plans))
                            return plans
                if rail_rate_limited:
                    break
            if rail_rate_limited:
                break

        for origin_station in origin_stations:
            if rail_rate_limited:
                break
            for destination_airport in destination_airports:
                for hub_airport in hub_airports:
                    hub_iata = airport_iata_for_candidate(hub_airport)
                    destination_iata = airport_iata_for_candidate(destination_airport)
                    if not hub_iata or not destination_iata:
                        continue
                    rail_result = search_rail_offers_with_enabled_provider_result(
                        RailSearchRequest(train_number="", origin_station=origin_station, destination_station=transfer_station.station_name, departure_date=day)
                    )
                    flight_result = search_flight_offers_with_enabled_provider_result(
                        FlightSearchRequest(origin_iata=hub_iata, destination_iata=destination_iata, departure_date=day, adults=1, currency_code="CNY", max_results=2, non_stop=None)
                    )
                    if not rail_result.offers or not flight_result.offers:
                        failure_messages.append(f"rail-flight via {transfer_station.station_name}: rail={rail_result.failure_message or len(rail_result.offers)} flight={flight_result.failure_message or len(flight_result.offers)}")
                        logger.info(
                            "rail_mixed_rail_flight_empty request_id=%s origin_station=%s transfer_station=%s failure_message=%s",
                            travel_request.request_id,
                            origin_station,
                            transfer_station.station_name,
                            failure_messages[-1],
                        )
                        if _rail_provider_error_code(failure_messages[-1]) == "RAIL_PROVIDER_RATE_LIMITED":
                            rail_rate_limited = True
                            break
                        continue
                    rail_segment = _rail_segment_from_offer(f"seg_mixed_rail_first_{len(plans) + 1}", rail_result.offers[0])
                    flight_segments = _flight_segments_from_offer(
                        segment_prefix=f"seg_mixed_flight_second_{len(plans) + 1}",
                        offer=flight_result.offers[0],
                        day=day,
                        origin_airport_name=hub_airport.airport_name,
                        destination_airport_name=destination_airport.airport_name,
                    )
                    if flight_segments and _has_connection(rail_segment, flight_segments[0], 120):
                        plan_index = len(plans) + 1
                        plans.append(
                            _plan(
                                f"plan_flight_rail_mixed_dynamic_{plan_index}",
                                f"Dynamic rail-flight via {transfer_station.city_name}",
                                PlanType.FLIGHT_RAIL_MIXED,
                                [
                                    taxi(f"seg_mixed_origin_station_{plan_index}", origin_text, rail_segment.origin_station, 38, 7800),
                                    rail_segment,
                                    taxi(f"seg_mixed_station_airport_{plan_index}", transfer_station.station_name, hub_airport.airport_name, 50, 9000),
                                    *flight_segments,
                                    taxi(f"seg_mixed_airport_dest_{plan_index}", destination_airport.airport_name, destination_text, 54, 13600),
                                ],
                                7.0,
                                RiskLevel.MEDIUM,
                                "Verified rail and flight provider offers",
                                "The rail and flight facts both come from enabled providers and pass a connection-time check.",
                            )
                        )
                        logger.info(
                            "rail_mixed_rail_flight_plan_created request_id=%s plan_id=%s transfer_city=%s rail_train=%s",
                            travel_request.request_id,
                            f"plan_flight_rail_mixed_dynamic_{plan_index}",
                            transfer_station.city_name,
                            rail_segment.train_number,
                        )
                        if len(plans) >= max_plans:
                            logger.info("rail_mixed_planner_complete request_id=%s plan_count=%s reason=max_plans", travel_request.request_id, len(plans))
                            return plans
                if rail_rate_limited:
                    break

    if not plans and failure_messages:
        collector.add_missing("mixed_core_fact")
        if any(_rail_provider_error_code(message) == "RAIL_PROVIDER_RATE_LIMITED" for message in failure_messages):
            _record_rail_provider_block(
                collector,
                failure_messages=failure_messages,
                missing_component="mixed_core_fact",
                impacted_plan_types=[PlanType.FLIGHT_RAIL_MIXED],
            )
    logger.info("rail_mixed_planner_complete request_id=%s plan_count=%s rail_rate_limited=%s", travel_request.request_id, len(plans), rail_rate_limited)
    return plans


def _flight_transfer_segment_ids(plan_id: str) -> tuple[str, str]:
    stable_ids = {
        "plan_flight_direct_shqd": ("seg_origin_airport", "seg_airport_dest"),
        "plan_flight_direct_bg": ("seg_origin_airport", "seg_airport_dest"),
        "plan_flight_transfer_shqd": ("seg_origin_airport_transfer", "seg_airport_dest_transfer"),
        "plan_flight_transfer_bg": ("seg_origin_airport_transfer", "seg_airport_dest_transfer"),
        "plan_flight_multi_airport_shqd": ("seg_origin_airport_multi", "seg_airport_dest_multi"),
        "plan_flight_multi_airport_bg": ("seg_origin_airport_multi", "seg_airport_dest_multi"),
    }
    return stable_ids.get(plan_id, (f"seg_origin_airport_{plan_id}", f"seg_airport_dest_{plan_id}"))


def _flight_plan_from_spec(
    spec: FlightPlanSpec,
    *,
    day,
    city_origin: str,
    city_destination: str,
    taxi,
) -> TravelPlan:
    origin_segment_id, destination_segment_id = _flight_transfer_segment_ids(spec.plan_id)
    flight_segments = [
        _flight(
            leg.segment_id,
            leg.flight_number,
            leg.origin_airport,
            leg.destination_airport,
            day,
            leg.departure_hour,
            leg.departure_minute,
            leg.arrival_hour,
            leg.arrival_minute,
            leg.base_fare_minor,
            previous_risk=leg.previous_flight_risk_available,
        )
        for leg in spec.legs
    ]
    first_airport = spec.legs[0].origin_airport
    last_airport = spec.legs[-1].destination_airport
    segments = [
        taxi(origin_segment_id, city_origin, first_airport, 52, 11800),
        *flight_segments,
        taxi(destination_segment_id, last_airport, city_destination, 54, 13600),
    ]
    return _plan(
        spec.plan_id,
        spec.plan_name,
        spec.plan_type,
        segments,
        spec.comfort_score,
        spec.risk_level,
        spec.risk_title,
        spec.risk_message,
    )


def _unsupported_route_result(
    travel_request: TravelRequest,
    route_nodes,
    collector: PlanningIssueCollector,
) -> tuple[list[TravelPlan], list[SourceFailure], list[str], list[PlanType], list[MissingPlanExplanation], list[str]]:
    impacted_types = [
        PlanType.DIRECT_RAIL,
        PlanType.TRANSFER_RAIL,
        PlanType.DIRECT_FLIGHT,
        PlanType.TRANSFER_FLIGHT,
        PlanType.FLIGHT_RAIL_MIXED,
    ]
    station_names = "、".join(candidate.station_name for candidate in route_nodes.station_candidates) or "暂无可用站点候选"
    airport_names = "、".join(candidate.airport_name for candidate in route_nodes.airport_candidates) or "暂无可用机场候选"
    user_message = f"当前 Planner 尚未覆盖 {travel_request.origin_text} 到 {travel_request.destination_text} 的门到门规划；已识别候选站点：{station_names}；候选机场：{airport_names}。"
    collector.add_missing("route_coverage")
    collector.add_warning(user_message)
    collector.add_source_failure(
        source_id="internal_calc",
        adapter_name="LocationResolver",
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.EXPLAIN_ONLY,
        error_code="ROUTE_COVERAGE_UNSUPPORTED",
        message=f"route coverage unsupported: {route_nodes.route_key}",
        user_visible_message=user_message,
        impacted_plan_types=impacted_types,
        source_used_id="internal_calc",
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
    )
    explanations = [
        MissingPlanExplanation(
            plan_type=plan_type,
            reason_code="ROUTE_COVERAGE_UNSUPPORTED",
            user_visible_message=user_message,
        )
        for plan_type in impacted_types
    ]
    return [], collector.failures, collector.missing_components, impacted_types, explanations, collector.warnings


def _transport_catalog_missing_result(
    travel_request: TravelRequest,
    route_nodes,
    collector: PlanningIssueCollector,
) -> tuple[list[TravelPlan], list[SourceFailure], list[str], list[PlanType], list[MissingPlanExplanation], list[str]]:
    impacted_types = [
        PlanType.DIRECT_RAIL,
        PlanType.TRANSFER_RAIL,
        PlanType.DIRECT_FLIGHT,
        PlanType.TRANSFER_FLIGHT,
        PlanType.FLIGHT_RAIL_MIXED,
    ]
    route_parts = route_nodes.route_key.split("_", 1)
    origin_city = route_parts[0] if route_parts else ""
    destination_city = route_parts[1] if len(route_parts) > 1 else ""
    origin_station_count = len([candidate for candidate in route_nodes.station_candidates if candidate.city_name == origin_city])
    destination_station_count = len([candidate for candidate in route_nodes.station_candidates if candidate.city_name == destination_city])
    missing_sides = []
    if not origin_station_count:
        missing_sides.append(f"出发城市 {origin_city or travel_request.origin_text}")
    if not destination_station_count:
        missing_sides.append(f"目的城市 {destination_city or travel_request.destination_text}")
    missing_text = "、".join(missing_sides) or "出发或目的城市"
    user_message = f"已解析出行地点，但交通节点目录缺少 {missing_text} 的可用铁路站点候选；当前不会编造站点，已阻断需要真实站点的方案。"
    collector.add_missing("transport_node_catalog")
    collector.add_warning(user_message)
    collector.add_source_failure(
        source_id="internal_calc",
        adapter_name="LocationResolver",
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
        error_code="TRANSPORT_NODE_CATALOG_MISSING",
        message=f"transport node catalog missing station candidates: {route_nodes.route_key}",
        user_visible_message=user_message,
        impacted_plan_types=impacted_types,
        source_used_id="internal_calc",
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
    )
    explanations = [
        MissingPlanExplanation(
            plan_type=plan_type,
            reason_code="TRANSPORT_NODE_CATALOG_MISSING",
            user_visible_message=user_message,
        )
        for plan_type in impacted_types
    ]
    return [], collector.failures, collector.missing_components, impacted_types, explanations, collector.warnings


def build_plans(travel_request: TravelRequest) -> tuple[list[TravelPlan], list[SourceFailure], list[str], list[PlanType], list[MissingPlanExplanation], list[str]]:
    day = travel_request.travel_date
    origin = travel_request.origin_text
    destination = travel_request.destination_text
    collector = PlanningIssueCollector(travel_request)

    def taxi(segment_id: str, origin: str, destination: str, minutes: int, cost_minor: int, option_id: str = "transfer_taxi") -> LocalTransferSegment:
        return _taxi(segment_id, origin, destination, minutes, cost_minor, option_id=option_id, collector=collector)

    route_nodes = planning_nodes_for_request(origin, destination)
    origin_city = resolve_location_city(origin) or ""
    destination_city = resolve_location_city(destination) or ""
    logger.info(
        "rail_planning_flow_start request_id=%s origin=%s destination=%s origin_city=%s destination_city=%s travel_date=%s",
        travel_request.request_id,
        origin,
        destination,
        origin_city,
        destination_city,
        day.isoformat(),
    )

    dynamic_rail_plans = _build_dynamic_direct_rail_plans(
        travel_request=travel_request,
        route_nodes=route_nodes,
        day=day,
        origin_text=origin,
        destination_text=destination,
        origin_city=origin_city,
        destination_city=destination_city,
        taxi=taxi,
        collector=collector,
    )
    dynamic_flight_plans = _build_dynamic_flight_plans(
        travel_request=travel_request,
        route_nodes=route_nodes,
        day=day,
        origin_text=origin,
        destination_text=destination,
        origin_city=origin_city,
        destination_city=destination_city,
        taxi=taxi,
        collector=collector,
    )
    dynamic_transfer_rail_plans = []
    if not dynamic_rail_plans and not collector.has_rail_rate_limit():
        dynamic_transfer_rail_plans = _build_dynamic_transfer_rail_plans(
            travel_request=travel_request,
            route_nodes=route_nodes,
            day=day,
            origin_text=origin,
            destination_text=destination,
            origin_city=origin_city,
            destination_city=destination_city,
            taxi=taxi,
            collector=collector,
            max_hubs=3,
        )
    dynamic_mixed_plans = []
    if not dynamic_rail_plans and not dynamic_flight_plans and not collector.has_rail_rate_limit():
        dynamic_mixed_plans = _build_dynamic_flight_rail_mixed_plans(
            travel_request=travel_request,
            route_nodes=route_nodes,
            day=day,
            origin_text=origin,
            destination_text=destination,
            origin_city=origin_city,
            destination_city=destination_city,
            taxi=taxi,
            collector=collector,
            max_hubs=2,
        )
    plans = [*dynamic_rail_plans, *dynamic_flight_plans, *dynamic_transfer_rail_plans, *dynamic_mixed_plans]
    logger.info(
        "rail_planning_flow_candidates request_id=%s direct_rail_count=%s transfer_rail_count=%s mixed_count=%s total_plan_count=%s rail_rate_limited=%s",
        travel_request.request_id,
        len(dynamic_rail_plans),
        len(dynamic_transfer_rail_plans),
        len(dynamic_mixed_plans),
        len(plans),
        collector.has_rail_rate_limit(),
    )
    if not plans and "rail_station_candidates" in collector.missing_components and "flight_airport_candidates" in collector.missing_components:
        return _transport_catalog_missing_result(travel_request, route_nodes, collector)
    if not plans and not collector.missing_components:
        return _unsupported_route_result(travel_request, route_nodes, collector)

    generated_types = {plan.plan_type for plan in plans}
    blocked_types = [PlanType.MULTI_TRANSFER_RAIL, PlanType.RAIL_TICKET_ENHANCEMENT, PlanType.MULTI_AIRPORT_FLIGHT]
    for plan_type in (PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL, PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT, PlanType.FLIGHT_RAIL_MIXED):
        if plan_type not in generated_types:
            blocked_types.append(plan_type)

    explanations: list[MissingPlanExplanation] = []
    if PlanType.DIRECT_RAIL not in generated_types:
        explanations.append(MissingPlanExplanation(plan_type=PlanType.DIRECT_RAIL, reason_code="CORE_FACT_UNAVAILABLE", user_visible_message=_direct_rail_block_message(collector)))
    if PlanType.TRANSFER_RAIL not in generated_types:
        explanations.append(MissingPlanExplanation(plan_type=PlanType.TRANSFER_RAIL, reason_code="CORE_FACT_UNAVAILABLE", user_visible_message="Dynamic rail transfer planner attempted provider-verified legs but found no connectable two-leg plan in this run."))
    explanations.extend(
        [
            MissingPlanExplanation(plan_type=PlanType.MULTI_TRANSFER_RAIL, reason_code="DYNAMIC_PLANNER_CAPABILITY_GAP", user_visible_message="Multi-transfer rail still needs stricter station-order and ticket-risk validation before it can be recommended."),
            MissingPlanExplanation(plan_type=PlanType.RAIL_TICKET_ENHANCEMENT, reason_code="DYNAMIC_PLANNER_CAPABILITY_GAP", user_visible_message="Ticket enhancement still requires verified stop sequence, fare and availability rules before it can be recommended."),
        ]
    )
    if PlanType.DIRECT_FLIGHT not in generated_types:
        explanations.append(MissingPlanExplanation(plan_type=PlanType.DIRECT_FLIGHT, reason_code="CORE_FACT_UNAVAILABLE", user_visible_message="Dynamic flight planner attempted provider offers but found no direct flight plan in this run."))
    if PlanType.TRANSFER_FLIGHT not in generated_types:
        explanations.append(MissingPlanExplanation(plan_type=PlanType.TRANSFER_FLIGHT, reason_code="CORE_FACT_UNAVAILABLE", user_visible_message="Dynamic flight planner accepts connecting flight offers, but no connecting offer was returned in this run."))
    explanations.append(MissingPlanExplanation(plan_type=PlanType.MULTI_AIRPORT_FLIGHT, reason_code="DYNAMIC_PLANNER_CAPABILITY_GAP", user_visible_message="Multi-airport flight combinations still need airport-transfer validation before they can be recommended."))
    if PlanType.FLIGHT_RAIL_MIXED not in generated_types:
        explanations.append(MissingPlanExplanation(plan_type=PlanType.FLIGHT_RAIL_MIXED, reason_code="CORE_FACT_UNAVAILABLE", user_visible_message="Dynamic flight-rail planner attempted provider-verified mixed legs but found no connectable plan in this run."))

    warnings = [
        *collector.warnings,
        "Planner assembles only provider-returned dynamic rail, flight, rail-transfer and flight-rail facts; unavailable families stay blocked instead of falling back to old templates.",
        "Prices and inventory are informational and must be confirmed on the final provider platform.",
        "The system shows read-only authorized-provider or redirect results only; it does not place orders or process payment.",
    ]
    return plans, collector.failures, collector.missing_components, blocked_types, explanations, warnings

def plan_trip(raw_or_request: str | TravelRequest, ctx: RequestContext) -> TravelPlanResponse:
    travel_request = parse_travel_request(raw_or_request, ctx) if isinstance(raw_or_request, str) else raw_or_request
    plans, failures, missing, blocked_types, explanations, warnings = build_plans(travel_request)
    for failure in failures:
        failure.trace_id = ctx.trace_id
        failure.correlation_id = ctx.correlation_id
    if not plans:
        missing = [*missing, "travel_plan"] if "travel_plan" not in missing else missing
        return TravelPlanResponse(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            idempotency_key=ctx.idempotency_key,
            planning_status=PlanningStatus.FAILED,
            progress=100,
            travel_request=travel_request,
            destination_presentation=resolve_destination_presentation(travel_request),
            plans=[],
            recommendation_result=None,
            source_failures=failures,
            missing_components=missing,
            blocked_plan_types=blocked_types,
            missing_plan_explanations=explanations,
            user_visible_warnings=[*warnings, "核心事实缺失，当前无法生成可用方案。"],
            async_job=None,
            generated_at=now_timepoint(),
        )
    candidate_pool = generate_candidate_plan_pool(plans, travel_request, explanations)
    candidate_plans = candidate_pool.llm_candidate_plans
    explanations = candidate_pool.missing_plan_explanations
    warnings = [*warnings, *candidate_pool.user_visible_warnings]
    constraint_analysis_enabled = os.getenv("TRAVEL_CONSTRAINT_ANALYSIS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    if not candidate_plans and constraint_analysis_enabled and candidate_pool.constraint_evaluations:
        constraint_analysis = build_constraint_analysis(candidate_pool.constraint_evaluations, failures)
        violation_types = sorted({violation.constraint_type for item in candidate_pool.constraint_evaluations for violation in item.violations})
        logger.info(
            "constraint_no_match request_id=%s raw_candidate_count=%s normal_candidate_count=0 alternative_count=%s violation_types=%s coverage=%s",
            ctx.request_id,
            len(plans),
            len(constraint_analysis.alternatives),
            violation_types,
            [item.status for item in constraint_analysis.coverage],
        )
        return TravelPlanResponse(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            idempotency_key=ctx.idempotency_key,
            planning_status=PlanningStatus.NO_MATCH,
            progress=100,
            travel_request=travel_request,
            destination_presentation=resolve_destination_presentation(travel_request),
            plans=[],
            recommendation_result=None,
            constraint_analysis=constraint_analysis,
            source_failures=failures,
            missing_components=missing,
            blocked_plan_types=blocked_types,
            missing_plan_explanations=explanations,
            user_visible_warnings=[*warnings, "没有候选满足全部硬约束；最近备选不会直接进入推荐或购票流程。"],
            async_job=None,
            generated_at=now_timepoint(),
        )
    if not candidate_plans and not constraint_analysis_enabled:
        missing = [*missing, "travel_plan"] if "travel_plan" not in missing else missing
        return TravelPlanResponse(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            idempotency_key=ctx.idempotency_key,
            planning_status=PlanningStatus.FAILED,
            progress=100,
            travel_request=travel_request,
            destination_presentation=resolve_destination_presentation(travel_request),
            plans=[],
            recommendation_result=None,
            source_failures=failures,
            missing_components=missing,
            blocked_plan_types=blocked_types,
            missing_plan_explanations=explanations,
            user_visible_warnings=[*warnings, "约束分析功能已关闭，沿用旧版无匹配失败行为。"],
            async_job=None,
            generated_at=now_timepoint(),
        )
    recommendation_result = None
    if candidate_plans:
        recommendation_result = recommend_with_validation(
            LLMRecommendationInput(
                request_id=ctx.request_id,
                travel_request=travel_request,
                candidate_plan_ids=[plan.plan_id for plan in candidate_plans],
                candidate_plans=candidate_plans,
            )
        )
    else:
        missing = [*missing, "recommendation_candidates"]
        warnings = [*warnings, "当前约束过滤后没有可进入 LLM 推荐的候选方案。"]
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
                adapter_name="LLMRecommendationProvider",
                handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
                error_code="LLM_RECOMMENDATION_UNAVAILABLE",
                retry_count=0,
                source_used_id=None,
                fallback_source_id=None,
                fallback_reason=None,
                fallback_used=False,
                failure_class=SourceFailureClass.AUXILIARY_DATA_FAILURE,
                message="LLM recommendation unavailable or invalid; deterministic recommendation fallback is disabled.",
                final_handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
                impacted_plan_types=list({plan.plan_type for plan in candidate_plans}),
                user_visible_message="真实 LLM 推荐不可用，暂不生成三张推荐卡；候选方案仍可查看。",
                occurred_at=now_timepoint(),
            ),
        ]
    elif "map_route" in missing:
        planning_status = PlanningStatus.PARTIAL
    return TravelPlanResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        planning_status=planning_status,
        progress=100,
        travel_request=travel_request,
        destination_presentation=resolve_destination_presentation(travel_request),
        plans=candidate_plans,
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
    if (
        request.change_type == "SEAT_TYPE"
        and request.application_scope == "RESULT_SET"
        and os.getenv("RESULT_SET_SEAT_PROPAGATION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    ):
        original_response = get_response_for_plan(existing.plan_id)
        if original_response is None:
            raise ValueError("current result set is unavailable for seat propagation")
        updated_response, preference_application, updated_plan = apply_rail_seat_to_result_set(
            original_response,
            target_plan_id=existing.plan_id,
            target_segment_id=request.target_segment_id,
            target_option_id=request.selected_option.option_id,
            ctx=ctx,
        )
        return RecalculateResponse(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            idempotency_key=request.idempotency_key,
            plan=updated_plan,
            change_summary=RecalculateChangeSummary(
                cost_delta=money_delta(updated_plan.cost_breakdown.total_cost.amount_minor - existing.cost_breakdown.total_cost.amount_minor),
                duration_delta_minutes=updated_plan.total_duration_minutes - existing.total_duration_minutes,
                comfort_delta=round(updated_plan.comfort_score.total_score - existing.comfort_score.total_score, 2),
                changed_fields=["travel_request.preferred_rail_seat", "plans", "recommendation_result"],
                message=preference_application.message,
            ),
            updated_response=updated_response,
            preference_application=preference_application,
            recommendation_result=updated_response.recommendation_result,
            generated_at=now_timepoint(),
        )
    plan = deepcopy(existing)
    target = next((segment for segment in plan.segments if segment.segment_id == request.target_segment_id), None)
    if target is None:
        raise ValueError("target_segment_id does not exist in plan")
    before_cost = plan.cost_breakdown.total_cost.amount_minor
    before_comfort = plan.comfort_score.total_score

    if request.change_type == "SEAT_TYPE":
        if not hasattr(target, "seat_options"):
            raise ValueError("target segment does not support rail seat options")
        assert_option_available(target, request.selected_option.option_id)
        target.selected_seat_option_id = request.selected_option.option_id
        plan.comfort_score.total_score = min(10, plan.comfort_score.total_score + (1.0 if "first" in request.selected_option.option_id else 2.0))
    elif request.change_type == "CABIN_TYPE":
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
        target.data_source = selected_transfer.data_source
        target.route_status = selected_transfer.route_status
        target.route_error_code = selected_transfer.route_error_code
        _sync_plan_selected_map_quality(plan)
        if request.selected_option.option_id == "transfer_subway":
            plan.comfort_score.total_score = max(0, plan.comfort_score.total_score - 0.5)
        elif request.selected_option.option_id == "transfer_bus":
            plan.comfort_score.total_score = max(0, plan.comfort_score.total_score - 0.9)
        elif request.selected_option.option_id == "transfer_walk":
            plan.comfort_score.total_score = max(0, plan.comfort_score.total_score - (0.2 if target.walking_distance_meters <= 1200 else 1.1))

    _refresh_plan_schedule(plan)
    refresh_plan_cost_and_quality(plan)
    update_plan(plan)
    after_cost = plan.cost_breakdown.total_cost.amount_minor
    recommendation_result = None
    original_response = get_response_for_plan(existing.plan_id)
    if request.recalculate_scope in {"PLAN_AND_RECOMMENDATION", "FULL_REEVALUATION"}:
        if original_response:
            scoped_plans = [plan if item.plan_id == plan.plan_id else item for item in original_response.plans]
            candidate_pool = generate_candidate_plan_pool(scoped_plans, original_response.travel_request, original_response.missing_plan_explanations)
            if candidate_pool.llm_candidate_plans:
                recommendation_result = recommend_with_validation(
                    LLMRecommendationInput(
                        request_id=ctx.request_id,
                        travel_request=original_response.travel_request,
                        candidate_plan_ids=[item.plan_id for item in candidate_pool.llm_candidate_plans],
                        candidate_plans=candidate_pool.llm_candidate_plans,
                    )
                )
    updated_response = None
    if request.change_type == "LOCAL_TRANSFER_MODE" and original_response is not None:
        updated_response = _updated_target_plan_snapshot(original_response, plan, recommendation_result)
    return RecalculateResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=request.idempotency_key,
        plan=plan,
        change_summary=RecalculateChangeSummary(
            cost_delta=money_delta(after_cost - before_cost),
            duration_delta_minutes=0 if request.change_type != "LOCAL_TRANSFER_MODE" else plan.total_duration_minutes - existing.total_duration_minutes,
            comfort_delta=round(plan.comfort_score.total_score - before_comfort, 2),
            changed_fields=["cost_breakdown", "comfort_score", "selected_option"],
            message="已基于后端返回的合法 option_id 完成重算。",
        ),
        updated_response=updated_response,
        recommendation_result=recommendation_result,
        generated_at=now_timepoint(),
    )


def _sync_plan_selected_map_quality(plan: TravelPlan) -> None:
    selected_degraded = any(
        isinstance(segment, LocalTransferSegment) and segment.route_status in {"RULE_ESTIMATED", "UNAVAILABLE"}
        for segment in plan.segments
    )
    warning = "当前选中的接驳路线暂未取得地图结果，已使用规则估算。"
    if selected_degraded:
        if "map_route" not in plan.data_quality.missing_components:
            plan.data_quality.missing_components.append("map_route")
        if warning not in plan.data_quality.warnings:
            plan.data_quality.warnings.append(warning)
    else:
        plan.data_quality.missing_components = [item for item in plan.data_quality.missing_components if item != "map_route"]
        plan.data_quality.warnings = [item for item in plan.data_quality.warnings if item != warning]


def _updated_target_plan_snapshot(
    original: TravelPlanResponse,
    updated_plan: TravelPlan,
    recommendation_result: RecommendationResult | None,
) -> TravelPlanResponse:
    snapshot = deepcopy(original)
    snapshot.plans = [updated_plan if plan.plan_id == updated_plan.plan_id else plan for plan in snapshot.plans]
    if recommendation_result is not None:
        snapshot.recommendation_result = recommendation_result
    has_degraded_selected_route = any(
        isinstance(segment, LocalTransferSegment) and segment.route_status in {"RULE_ESTIMATED", "UNAVAILABLE"}
        for plan in snapshot.plans
        for segment in plan.segments
    )
    warning = "当前选中的接驳路线暂未取得地图结果，已使用规则估算。"
    if has_degraded_selected_route:
        snapshot.planning_status = PlanningStatus.PARTIAL
        if "map_route" not in snapshot.missing_components:
            snapshot.missing_components.append("map_route")
        if warning not in snapshot.user_visible_warnings:
            snapshot.user_visible_warnings.append(warning)
    else:
        snapshot.missing_components = [item for item in snapshot.missing_components if item != "map_route"]
        snapshot.user_visible_warnings = [
            item
            for item in snapshot.user_visible_warnings
            if not ("接驳路线" in item and "规则估算" in item)
        ]
        if snapshot.recommendation_result is not None:
            snapshot.planning_status = PlanningStatus.COMPLETE
    snapshot.generated_at = now_timepoint()
    return TravelPlanResponse.model_validate(snapshot.model_dump())
