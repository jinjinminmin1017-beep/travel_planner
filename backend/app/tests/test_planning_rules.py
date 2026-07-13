from datetime import date, datetime

from app.data_sources.flight_providers import FlightOffer, FlightOfferCabinOption, FlightOfferSegment, FlightProviderSearchResult, flight_data_source_metadata
from app.data_sources.rail_providers import RailOffer, RailProviderSearchResult, rail_data_source_metadata
from app.core.context import RequestContext
from app.models.schemas import AirportCandidate, GeoPoint, LocalTransferSegment, PlanType, RecommendationType, SeatOption, StationCandidate, TravelHardConstraints, TravelRequest, TravelSoftPreferences, money
from app.services.intent_parser import parse_travel_request
from app.services.location_resolver import INTERNAL_LOCATION_SOURCE, PlanningRouteNodes
from app.services.planner import build_plans
from app.services.planning_rules import assert_option_available, candidate_plans_for_recommendation


def _request():
    ctx = RequestContext("req_rules", "trace_rules", "corr_rules", "idem_rules")
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。",
        ctx,
    )


def _beijing_guangzhou_request():
    ctx = RequestContext("req_bg", "trace_bg", "corr_bg", "idem_bg")
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从北京到广州，帮我找最舒服的方式。",
        ctx,
    )


def _shanghai_wuhan_request():
    ctx = RequestContext("req_sw", "trace_sw", "corr_sw", "idem_sw")
    return parse_travel_request(
        "6.26号上午，从上海静安寺到武汉天地",
        ctx,
    )


def _assert_dynamic_provider_only(plans):
    plan_ids = {plan.plan_id for plan in plans}
    assert plan_ids
    assert all(plan_id.startswith(("plan_rail_direct_dynamic", "plan_flight_dynamic", "plan_rail_transfer_dynamic", "plan_flight_rail_mixed_dynamic")) for plan_id in plan_ids)
    assert not any(plan_id.endswith("_shqd") or plan_id.endswith("_bg") for plan_id in plan_ids)
    assert not any("ticket" in plan_id or "buy_short" in plan_id for plan_id in plan_ids)


def _station(name: str, city: str) -> StationCandidate:
    return StationCandidate(
        station_id=f"station_{name}",
        station_name=name,
        city_name=city,
        location=GeoPoint(name=name, latitude=30.0, longitude=120.0),
        estimated_transfer_duration_minutes=20,
        estimated_transfer_cost=money(1000, estimated=True),
        ranking_reasons=["test"],
        data_source=INTERNAL_LOCATION_SOURCE,
    )


def _airport(name: str, city: str) -> AirportCandidate:
    return AirportCandidate(
        airport_id=f"airport_{name}",
        airport_name=name,
        city_name=city,
        location=GeoPoint(name=name, latitude=30.0, longitude=120.0),
        estimated_transfer_duration_minutes=40,
        estimated_transfer_cost=money(5000, estimated=True),
        ranking_reasons=["test"],
        data_source=INTERNAL_LOCATION_SOURCE,
    )


def _rail_offer(origin: str, destination: str, day: date, dep_h: int, arr_h: int) -> RailOffer:
    source = rail_data_source_metadata("rail_12306_public_query", "12306 Public Ticket Query")
    departure = datetime.combine(day, datetime.min.time()).replace(hour=dep_h)
    arrival = datetime.combine(day, datetime.min.time()).replace(hour=arr_h)
    return RailOffer(
        train_number=f"G{dep_h}{arr_h}",
        origin_station=origin,
        destination_station=destination,
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=int((arrival - departure).total_seconds() // 60),
        stop_sequence=[origin, destination],
        seat_options=[SeatOption(option_id="seat_second", seat_type="Second", price=money(30000), availability="AVAILABLE", source_option_version="test", data_source=source)],
        data_source=source,
    )


def _flight_offer(origin_iata: str, destination_iata: str, day: date, dep_h: int, arr_h: int) -> FlightOffer:
    source = flight_data_source_metadata("airline_mu_public_query", "China Eastern Official Public Flight Query", evidence_id="fixture")
    departure = datetime.combine(day, datetime.min.time()).replace(hour=dep_h)
    arrival = datetime.combine(day, datetime.min.time()).replace(hour=arr_h)
    return FlightOffer(
        offer_id=f"{origin_iata}_{destination_iata}",
        source="TEST",
        total_price=money(60000),
        currency="CNY",
        segments=[FlightOfferSegment(carrier_code="MU", flight_number="1", origin_iata=origin_iata, destination_iata=destination_iata, departure_at=departure, arrival_at=arrival, duration=None)],
        validating_airline_codes=["MU"],
        raw_offer={"id": "test", "available": True},
        data_source=source,
        cabin_options=[
            FlightOfferCabinOption(
                option_id="cabin_economy",
                cabin_type="ECONOMY",
                price=money(60000),
                availability="AVAILABLE",
                source_option_version="fixture_flight_economy",
                inventory_evidence="fixture_available",
            )
        ],
        evidence_id="fixture",
    )


def test_candidate_filter_only_uses_dynamic_provider_plans():
    plans, *_ = build_plans(_request())
    candidate_ids = {plan.plan_id for plan in candidate_plans_for_recommendation(plans)}

    assert candidate_ids
    assert all(plan_id.startswith(("plan_rail_direct_dynamic", "plan_flight_dynamic", "plan_rail_transfer_dynamic", "plan_flight_rail_mixed_dynamic")) for plan_id in candidate_ids)
    assert "plan_blocked_shqd" not in candidate_ids
    assert "plan_ticket_a_shqd" not in candidate_ids
    assert "plan_buy_short_shqd" not in candidate_ids
    assert "plan_ticket_s_shqd" not in candidate_ids


def test_non_sample_route_uses_dynamic_direct_rail_without_old_families():
    plans, failures, missing, blocked_types, explanations, warnings = build_plans(_beijing_guangzhou_request())
    candidate_ids = {plan.plan_id for plan in candidate_plans_for_recommendation(plans)}

    _assert_dynamic_provider_only(plans)
    assert candidate_ids == {plan.plan_id for plan in plans}
    assert len(candidate_ids) <= 15
    assert not any(failure.source_id == "rail_12306_public_query" for failure in failures)
    assert missing == []
    assert PlanType.TRANSFER_RAIL in blocked_types
    assert PlanType.MULTI_TRANSFER_RAIL in blocked_types
    assert PlanType.DIRECT_FLIGHT not in blocked_types
    assert any(plan.plan_type == PlanType.DIRECT_FLIGHT for plan in plans)
    assert any(item.reason_code == "DYNAMIC_PLANNER_CAPABILITY_GAP" for item in explanations)
    assert any("old templates" in warning for warning in warnings)

    rail_direct = plans[0]
    rail_segment = next(segment for segment in rail_direct.segments if hasattr(segment, "origin_station"))
    assert rail_segment.origin_station == "北京西"
    assert rail_segment.destination_station == "广州南"


def test_wuhan_route_uses_dynamic_direct_rail_candidates():
    plans, failures, missing, _, _, _ = build_plans(_shanghai_wuhan_request())

    _assert_dynamic_provider_only(plans)
    assert not any(failure.source_id == "rail_12306_public_query" for failure in failures)
    assert "route_coverage" not in missing
    rail_segment = next(segment for segment in plans[0].segments if hasattr(segment, "origin_station"))
    assert rail_segment.origin_station == "上海虹桥"
    assert rail_segment.destination_station == "武汉"


def test_dynamic_transfer_rail_planner_builds_connectable_two_leg_plan(monkeypatch):
    day = date(2026, 6, 27)
    route_nodes = PlanningRouteNodes(
        route_key="OriginCity_DestCity",
        supported=False,
        city_origin="OriginCity",
        city_destination="DestCity",
        start_station="OriginStation",
        end_station="DestStation",
        start_airport="",
        end_airport="",
        rail_train="",
        flight_no="",
        station_candidates=[_station("OriginStation", "OriginCity"), _station("DestStation", "DestCity")],
        airport_candidates=[],
    )
    monkeypatch.setattr("app.services.planner.planning_nodes_for_request", lambda origin, destination: route_nodes)
    monkeypatch.setattr("app.services.planner.resolve_location_city", lambda place: "OriginCity" if place == "origin" else "DestCity")
    monkeypatch.setattr("app.services.planner.transfer_station_candidates_between", lambda origin_city, destination_city, limit=6: [_station("HubStation", "HubCity")])
    monkeypatch.setattr("app.services.local_transfer_engine.resolve_location_point", lambda place: GeoPoint(name=place, latitude=30.0, longitude=120.0))
    monkeypatch.setattr("app.services.local_transfer_engine.resolve_location_city", lambda place: "TestCity")

    def fake_rail(request, environment=None):
        if request.origin_station == "OriginStation" and request.destination_station == "HubStation":
            return RailProviderSearchResult(offers=[_rail_offer("OriginStation", "HubStation", day, 8, 10)], attempted_source_ids=["rail_12306_public_query"])
        if request.origin_station == "HubStation" and request.destination_station == "DestStation":
            return RailProviderSearchResult(offers=[_rail_offer("HubStation", "DestStation", day, 12, 15)], attempted_source_ids=["rail_12306_public_query"])
        return RailProviderSearchResult(offers=[], attempted_source_ids=["rail_12306_public_query"], failure_message="empty response")

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_rail)
    request = TravelRequest(
        request_id="req_transfer_rail",
        raw_user_input="origin to destination",
        origin_text="origin",
        destination_text="destination",
        travel_date=day,
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, *_ = build_plans(request)

    assert any(plan.plan_type == PlanType.TRANSFER_RAIL for plan in plans)


def test_dynamic_flight_rail_mixed_planner_builds_connectable_plan(monkeypatch):
    day = date(2026, 6, 27)
    origin_airport = _airport("OriginAirport", "OriginCity")
    destination_airport = _airport("DestAirport", "DestCity")
    hub_airport = _airport("HubAirport", "HubCity")
    route_nodes = PlanningRouteNodes(
        route_key="OriginCity_DestCity",
        supported=False,
        city_origin="OriginCity",
        city_destination="DestCity",
        start_station="OriginStation",
        end_station="DestStation",
        start_airport="OriginAirport",
        end_airport="DestAirport",
        rail_train="",
        flight_no="",
        station_candidates=[_station("OriginStation", "OriginCity"), _station("DestStation", "DestCity")],
        airport_candidates=[origin_airport, destination_airport],
    )
    monkeypatch.setattr("app.services.planner.planning_nodes_for_request", lambda origin, destination: route_nodes)
    monkeypatch.setattr("app.services.planner.resolve_location_city", lambda place: "OriginCity" if place == "origin" else "DestCity")
    monkeypatch.setattr("app.services.planner.transfer_station_candidates_between", lambda origin_city, destination_city, limit=6: [_station("HubStation", "HubCity")])
    monkeypatch.setattr("app.services.planner.airport_candidates_for_city", lambda place, limit=2: [hub_airport] if place == "HubCity" else [])
    monkeypatch.setattr("app.services.local_transfer_engine.resolve_location_point", lambda place: GeoPoint(name=place, latitude=30.0, longitude=120.0))
    monkeypatch.setattr("app.services.local_transfer_engine.resolve_location_city", lambda place: "TestCity")
    monkeypatch.setattr(
        "app.services.planner.airport_iata_for_candidate",
        lambda candidate: {"OriginAirport": "OOO", "HubAirport": "HHH", "DestAirport": "DDD"}.get(candidate.airport_name),
    )

    def fake_rail(request, environment=None):
        if request.origin_station == "OriginStation" and request.destination_station == "HubStation":
            return RailProviderSearchResult(offers=[_rail_offer("OriginStation", "HubStation", day, 8, 10)], attempted_source_ids=["rail_12306_public_query"])
        return RailProviderSearchResult(offers=[], attempted_source_ids=["rail_12306_public_query"], failure_message="empty response")

    def fake_flight(request, environment=None):
        if request.origin_iata == "HHH" and request.destination_iata == "DDD":
            return FlightProviderSearchResult(offers=[_flight_offer("HHH", "DDD", day, 13, 15)], attempted_source_ids=["airline_mu_public_query"])
        return FlightProviderSearchResult(offers=[], attempted_source_ids=["airline_mu_public_query"], failure_message="empty response")

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_rail)
    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_flight)
    request = TravelRequest(
        request_id="req_mixed",
        raw_user_input="origin to destination",
        origin_text="origin",
        destination_text="destination",
        travel_date=day,
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, *_ = build_plans(request)

    assert any(plan.plan_type == PlanType.FLIGHT_RAIL_MIXED for plan in plans)


def test_missing_transport_node_catalog_is_not_reported_as_route_coverage(monkeypatch):
    route_nodes = PlanningRouteNodes(
        route_key="上海_虚构城",
        supported=False,
        city_origin="上海",
        city_destination="虚构城",
        start_station="上海虹桥",
        end_station="",
        start_airport="",
        end_airport="",
        rail_train="",
        flight_no="",
        station_candidates=[
            StationCandidate(
                station_id="sha_hongqiao",
                station_name="上海虹桥",
                city_name="上海",
                location=GeoPoint(name="上海虹桥站", latitude=31.2, longitude=121.3269),
                estimated_transfer_duration_minutes=20,
                estimated_transfer_cost=money(600, estimated=True),
                ranking_reasons=["测试候选"],
                data_source=INTERNAL_LOCATION_SOURCE,
            )
        ],
        airport_candidates=[],
    )
    monkeypatch.setattr("app.services.planner.planning_nodes_for_request", lambda origin, destination: route_nodes)
    monkeypatch.setattr("app.services.planner.resolve_location_city", lambda place: "上海" if place == "上海" else "虚构城")
    travel_request = TravelRequest(
        request_id="req_missing_catalog",
        raw_user_input="2026-06-26 上海到虚构城",
        origin_text="上海",
        destination_text="虚构城",
        travel_date=date(2026, 6, 26),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, _, explanations, warnings = build_plans(travel_request)

    assert plans == []
    assert "rail_station_candidates" in missing
    assert "transport_node_catalog" in missing
    assert "route_coverage" not in missing
    assert failures[0].error_code == "TRANSPORT_NODE_CATALOG_MISSING"
    assert explanations[0].reason_code == "TRANSPORT_NODE_CATALOG_MISSING"
    assert any("不会编造站点" in warning for warning in warnings)


def test_ticket_enhancement_is_blocked_until_dynamic_validation_exists():
    plans, _, _, blocked_types, explanations, _ = build_plans(_request())

    _assert_dynamic_provider_only(plans)
    assert PlanType.RAIL_TICKET_ENHANCEMENT in blocked_types
    assert any(
        item.plan_type == PlanType.RAIL_TICKET_ENHANCEMENT and item.reason_code == "DYNAMIC_PLANNER_CAPABILITY_GAP"
        for item in explanations
    )


def test_option_validation_on_dynamic_rail_plan():
    plans, *_ = build_plans(_request())
    direct = plans[0]
    rail_segment = next(segment for segment in direct.segments if hasattr(segment, "seat_options"))
    transfer_segment = next(segment for segment in direct.segments if isinstance(segment, LocalTransferSegment))

    assert_option_available(rail_segment, "seat_first")
    assert_option_available(transfer_segment, "transfer_subway")
