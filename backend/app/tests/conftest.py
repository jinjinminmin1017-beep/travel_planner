from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.data_sources.config_loader import reset_data_source_settings_cache
from app.data_sources.flight_providers import FlightOffer, FlightOfferCabinOption, FlightOfferSegment, FlightProviderSearchResult, flight_data_source_metadata
from app.data_sources.map_providers import MapRouteEstimate, MapRouteProviderResult, data_source_metadata
from app.data_sources.rail_providers import RailOffer, RailProviderSearchResult, rail_data_source_metadata
from app.models.schemas import GeoPoint, SeatOption, money
from app.services.location_resolver import LocationPointResolution

SHANGHAI_TZ = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def deterministic_data_source_env(monkeypatch):
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    for raw_line in env_example.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "APP_ENV" or key == "TRAVEL_DATA_SOURCE_IDS" or key.startswith("TRAVEL_SOURCE_"):
            if value:
                monkeypatch.setenv(key, value)
            else:
                monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("app.data_sources.config_loader._ENV_LOADED", True)
    reset_data_source_settings_cache()
    yield
    reset_data_source_settings_cache()


@pytest.fixture(autouse=True)
def fake_real_flight_provider_for_planner(monkeypatch):
    def fake_search(request, environment=None):
        origin_iata = (
            request.allowed_origin_airport_iatas[0]
            if getattr(request, "allowed_origin_airport_iatas", ())
            else request.origin_iata
        )
        destination_iata = (
            request.allowed_destination_airport_iatas[0]
            if getattr(request, "allowed_destination_airport_iatas", ())
            else request.destination_iata
        )
        carrier = "CZ" if origin_iata == "PEK" else "MU"
        number = "3102" if carrier == "CZ" else "5511"
        source_id = "airline_cz_public_query" if carrier == "CZ" else "airline_mu_public_query"
        source_name = "China Southern Official Public Flight Query" if carrier == "CZ" else "China Eastern Official Public Flight Query"
        return FlightProviderSearchResult(
            offers=[
                FlightOffer(
                    offer_id=f"test_real_{carrier.lower()}",
                    source="TEST_REAL_PROVIDER",
                    total_price=money(88800 if carrier == "MU" else 108800),
                    currency="CNY",
                    segments=[
                        FlightOfferSegment(
                            carrier_code=carrier,
                            flight_number=number,
                            origin_iata=origin_iata,
                            destination_iata=destination_iata,
                            departure_at=datetime.combine(request.departure_date, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(hour=11, minute=20),
                            arrival_at=datetime.combine(request.departure_date, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(hour=13, minute=0),
                            duration="PT1H40M",
                        )
                    ],
                    validating_airline_codes=[carrier],
                    raw_offer={"id": f"test_real_{carrier.lower()}", "available": True},
                    data_source=flight_data_source_metadata(source_id, source_name, evidence_id=f"fixture_{carrier.lower()}"),
                    cabin_options=[
                        FlightOfferCabinOption(
                            option_id="cabin_economy",
                            cabin_type="ECONOMY",
                            price=money(88800 if carrier == "MU" else 108800),
                            availability="AVAILABLE",
                            source_option_version=f"fixture_{carrier.lower()}_economy",
                            inventory_evidence="fixture_available",
                        )
                    ],
                    evidence_id=f"fixture_{carrier.lower()}",
                )
            ],
            attempted_source_ids=[source_id],
        )

    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_search)


@pytest.fixture(autouse=True)
def fake_real_map_provider_for_planner(monkeypatch):
    def fake_estimate(request, environment=None):
        mode = request.mode.value if hasattr(request.mode, "value") else str(request.mode)
        base_minutes = {
            "TAXI": 38,
            "SUBWAY": 56,
            "BUS": 66,
            "WALK": 80,
        }.get(mode, 40)
        base_cost = {
            "TAXI": 7800,
            "SUBWAY": 900,
            "BUS": 500,
            "WALK": 0,
        }.get(mode, 1000)
        estimate = MapRouteEstimate(
            distance_meters=base_minutes * 650,
            duration_minutes=base_minutes,
            estimated_cost=money(base_cost, estimated=True),
            summary="test real map provider route",
            data_source=data_source_metadata("amap_route", "AMap Route Planning API"),
        )
        return MapRouteProviderResult(estimate=estimate, attempted_source_ids=["amap_route"])

    monkeypatch.setattr("app.services.planner.estimate_route_with_enabled_provider_result", fake_estimate)


@pytest.fixture(autouse=True)
def fake_verified_location_resolution_for_planner(monkeypatch):
    def fake_resolve(place, city_context=None, environment=None):
        city = city_context or ("上海" if "上海" in place else "武汉" if "武汉" in place or place in {"武汉", "汉口"} else "测试城市")
        point = GeoPoint(name=place, latitude=30.0, longitude=120.0)
        return LocationPointResolution(
            query=place,
            city_context=city,
            status="RESOLVED",
            point=point,
            source_id="test_verified_location",
            candidates=[],
            attempted_source_ids=["test_verified_location"],
        )

    monkeypatch.setattr("app.services.local_transfer_engine.resolve_location_point", fake_resolve)


@pytest.fixture(autouse=True)
def fake_real_rail_provider_for_planner(monkeypatch):
    def fake_search(request, environment=None):
        source = rail_data_source_metadata("rail_12306_public_query", "12306 Public Ticket Query")
        departure = datetime.combine(request.departure_date, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(hour=9, minute=48)
        arrival = datetime.combine(request.departure_date, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(hour=15, minute=38)
        train_number = request.train_number or "G900"
        base_minor = 52600 if train_number.startswith("G") else 30000
        return RailProviderSearchResult(
            offers=[
                RailOffer(
                    train_number=train_number,
                    origin_station=request.origin_station,
                    destination_station=request.destination_station,
                    departure_at=departure,
                    arrival_at=arrival,
                    duration_minutes=int((arrival - departure).total_seconds() // 60),
                    stop_sequence=[request.origin_station, request.destination_station],
                    seat_options=[
                        SeatOption(option_id="seat_second", seat_type="二等座", price=money(base_minor), availability="AVAILABLE", source_option_version="rail_12306_test", data_source=source),
                        SeatOption(option_id="seat_first", seat_type="一等座", price=money(base_minor + 22000), availability="AVAILABLE", source_option_version="rail_12306_test", data_source=source),
                        SeatOption(option_id="seat_business", seat_type="商务座", price=money(base_minor + 62000), availability="LIMITED", source_option_version="rail_12306_test", data_source=source),
                    ],
                    data_source=source,
                )
            ],
            attempted_source_ids=["rail_12306_public_query"],
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_search)
