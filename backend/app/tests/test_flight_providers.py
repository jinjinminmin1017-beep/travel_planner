from datetime import date, datetime

import pytest

from app.data_sources.flight_providers import (
    FlightOffer,
    FlightOfferCabinOption,
    FlightOfferSegment,
    FlightProviderError,
    FlightProviderSearchResult,
    FlightSearchRequest,
    FlightStateRequest,
    OfficialAirlinePublicQueryProvider,
    OpenSkyStatesProvider,
    build_enabled_flight_providers,
    flight_data_source_metadata,
    price_flight_offer_with_enabled_provider_result,
    search_flight_offers_with_enabled_provider_result,
)
from app.models.schemas import PlanType, RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences, money
from app.services.planner import build_plans


@pytest.fixture(autouse=True)
def clear_flight_source_env(monkeypatch):
    monkeypatch.setattr("app.data_sources.config_loader._ENV_LOADED", True)
    for source_id in ("AIRLINE_MU_PUBLIC_QUERY", "AIRLINE_CZ_PUBLIC_QUERY", "AIRLINE_SC_PUBLIC_QUERY"):
        for suffix in ("ENABLED", "LICENSE_STATUS", "QPS_LIMIT", "COMMERCIAL_ALLOWED", "BASE_URL", "SEARCH_PATH", "USER_AGENT", "CACHE_TTL_SECONDS"):
            monkeypatch.delenv(f"TRAVEL_SOURCE_{source_id}_{suffix}", raising=False)
    monkeypatch.delenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", raising=False)
    monkeypatch.delenv("TRAVEL_FLIGHT_SNAPSHOT_SQLITE_PATH", raising=False)


class _FakeResponse:
    def __init__(self, payload=None, *, text: str | None = None, content_type: str = "application/json"):
        self.payload = payload
        self.text = text if text is not None else ""
        self.headers = {"content-type": content_type}
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        if self.payload is None:
            raise ValueError("no json payload")
        return self.payload


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response


def test_official_airline_public_provider_maps_available_cabin_offer(monkeypatch):
    monkeypatch.setenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", "disabled")
    client = _FakeClient(_FakeResponse(_public_offer_payload()))
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU", "FM"),
        client=client,
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
    )

    offers = provider.search_offers(
        FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21), max_results=3, non_stop=True)
    )

    assert client.calls[0][0] == "GET"
    assert client.calls[0][1] == "https://example.test/api/flight/search"
    assert client.calls[0][2]["params"]["origin"] == "SHA"
    assert client.calls[0][2]["params"]["destination"] == "TAO"
    assert client.calls[0][2]["params"]["nonStop"] == "true"
    offer = offers[0]
    assert offer.offer_id == "mu_5511_20260521"
    assert offer.total_price.amount_minor == 94000
    assert offer.data_source.source_id == "airline_mu_public_query"
    assert offer.data_source.api_version.startswith("public_frontend_snapshot:")
    assert offer.segments[0].carrier_code == "MU"
    assert offer.segments[0].flight_number == "5511"
    assert offer.cabin_options[0].cabin_type == "ECONOMY"
    assert offer.cabin_options[0].availability == "LIMITED"
    assert offer.cabin_options[0].remaining_count == 3


def test_official_airline_public_provider_reads_html_embedded_payload(monkeypatch):
    monkeypatch.setenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", "disabled")
    html = '<html><script id="flight-offers-json" type="application/json">{"offers":[{"id":"mu_html","available":true,"flightNumber":"MU5511","origin":"SHA","destination":"TAO","departureTime":"2026-05-21T11:20:00+08:00","arrivalTime":"2026-05-21T13:00:00+08:00","price":{"total":"940.00","currency":"CNY"}}]}</script></html>'
    client = _FakeClient(_FakeResponse(text=html, content_type="text/html"))
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=client,
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
    )

    offers = provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))

    assert len(offers) == 1
    assert offers[0].offer_id == "mu_html"
    assert offers[0].cabin_options[0].availability == "AVAILABLE"


def test_public_airline_provider_filters_sold_out_and_missing_price(monkeypatch):
    monkeypatch.setenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", "disabled")
    payload = {
        "offers": [
            {
                "id": "sold_out",
                "flightNumber": "MU5511",
                "origin": "SHA",
                "destination": "TAO",
                "departureTime": "2026-05-21T11:20:00+08:00",
                "arrivalTime": "2026-05-21T13:00:00+08:00",
                "available": False,
                "price": {"total": "940.00", "currency": "CNY"},
            },
            {
                "id": "missing_price",
                "flightNumber": "MU5511",
                "origin": "SHA",
                "destination": "TAO",
                "departureTime": "2026-05-21T11:20:00+08:00",
                "arrivalTime": "2026-05-21T13:00:00+08:00",
                "available": True,
            },
        ]
    }
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=_FakeClient(_FakeResponse(payload)),
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
    )

    offers = provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))

    assert offers == []


def test_public_airline_provider_rejects_base_url_outside_allowlist(monkeypatch):
    monkeypatch.setenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", "disabled")
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=_FakeClient(_FakeResponse(_public_offer_payload())),
        base_url="https://example.test",
        cache_ttl_seconds=0,
    )

    with pytest.raises(FlightProviderError, match="outside the source allowlist"):
        provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))


def test_enabled_public_airline_provider_requires_flag_approval_and_base_url(monkeypatch):
    assert build_enabled_flight_providers("DEV") == []

    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_LICENSE_STATUS", "APPROVED")
    providers = build_enabled_flight_providers("DEV")

    assert [provider.source_id for provider in providers] == ["airline_mu_public_query"]
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)),
        environment="DEV",
    )
    assert result.offers == []
    assert result.attempted_source_ids == ["airline_mu_public_query"]
    assert "base URL is not configured" in result.failure_message


def test_flight_search_result_reports_disabled_provider_when_not_configured():
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="WNZ", departure_date=date(2026, 6, 28)),
        environment="DEV",
    )

    assert result.offers == []
    assert result.attempted_source_ids == ["airline_mu_public_query", "airline_cz_public_query", "airline_sc_public_query"]
    assert result.failure_message == "no enabled public airline flight provider"


def test_price_wrapper_keeps_self_harvest_offer_without_second_provider():
    offer = _flight_offer("SHA", "TAO", date(2026, 5, 21), 11, 13)

    result = price_flight_offer_with_enabled_provider_result(offer)

    assert result.offer is offer
    assert result.attempted_source_ids == ["airline_mu_public_query"]
    assert result.failure_message is None


def test_opensky_states_maps_real_response():
    class _OpenSkyClient:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return _FakeResponse(
                {
                    "time": 1780531000,
                    "states": [
                        [
                            "34310d",
                            "BCS116  ",
                            "Spain",
                            1780530999,
                            1780530999,
                            9.7529,
                            51.5788,
                            9723.12,
                            False,
                            207.75,
                            251.97,
                            2.6,
                            None,
                            9890.76,
                            "1000",
                            False,
                            0,
                        ]
                    ],
                }
            )

    client = _OpenSkyClient()
    provider = OpenSkyStatesProvider(client=client, base_url="https://example.test")
    states = provider.get_states(FlightStateRequest(lamin=45, lomin=5, lamax=55, lomax=15))

    assert client.calls[0][0] == "https://example.test/api/states/all"
    assert client.calls[0][1]["params"]["lamin"] == 45
    assert len(states) == 1
    assert states[0].icao24 == "34310d"
    assert states[0].callsign == "BCS116"
    assert states[0].origin_country == "Spain"
    assert states[0].longitude == 9.7529
    assert states[0].latitude == 51.5788
    assert states[0].data_source.source_id == "opensky_states"


def test_opensky_state_provider_is_enabled_by_default():
    from app.data_sources.flight_providers import build_enabled_flight_state_providers

    providers = build_enabled_flight_state_providers("DEV")
    assert [provider.source_id for provider in providers] == ["opensky_states"]


def test_planner_runtime_no_longer_generates_legacy_flight_templates(monkeypatch):
    called = False

    def fake_search(request, environment=None):
        nonlocal called
        called = True
        return FlightProviderSearchResult(offers=[], attempted_source_ids=["airline_mu_public_query"], failure_message="should not be called")

    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_search)
    request = TravelRequest(
        request_id="req_real_flight",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.MOST_COMFORTABLE, RecommendationType.CHEAPEST, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(prefer_comfort=True),
    )

    plans, failures, missing, blocked_types, explanations, _ = build_plans(request)

    assert plans
    assert called is True
    assert not any(any(getattr(segment, "segment_type", None) == "FLIGHT" for segment in plan.segments) for plan in plans)
    assert "flight_core_fact" in missing
    assert any(failure.source_id == "airline_mu_public_query" for failure in failures)
    assert PlanType.DIRECT_FLIGHT in blocked_types
    assert any(item.plan_type == PlanType.DIRECT_FLIGHT and item.reason_code == "CORE_FACT_UNAVAILABLE" for item in explanations)


def test_planner_blocks_flight_plans_when_real_flight_provider_is_empty(monkeypatch):
    def fake_empty_search(request, environment=None):
        return FlightProviderSearchResult(offers=[], attempted_source_ids=["airline_mu_public_query"], failure_message="empty real response")

    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_empty_search)
    request = TravelRequest(
        request_id="req_no_simulated_fallback",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.MOST_COMFORTABLE, RecommendationType.CHEAPEST, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(prefer_comfort=True),
    )

    plans, failures, missing, blocked_types, explanations, _ = build_plans(request)

    assert plans
    assert not any(any(getattr(segment, "segment_type", None) == "FLIGHT" for segment in plan.segments) for plan in plans)
    assert "flight_core_fact" in missing
    assert PlanType.DIRECT_FLIGHT in blocked_types
    assert any(item.plan_type == PlanType.DIRECT_FLIGHT and item.reason_code == "CORE_FACT_UNAVAILABLE" for item in explanations)
    assert any(failure.source_id == "airline_mu_public_query" for failure in failures)


def _public_offer_payload():
    return {
        "offers": [
            {
                "id": "mu_5511_20260521",
                "source": "MU_PUBLIC_FRONTEND",
                "segments": [
                    {
                        "carrierCode": "MU",
                        "flightNumber": "5511",
                        "origin": "SHA",
                        "destination": "TAO",
                        "departureTime": "2026-05-21T11:20:00+08:00",
                        "arrivalTime": "2026-05-21T13:00:00+08:00",
                        "duration": "PT1H40M",
                    }
                ],
                "cabins": [
                    {
                        "optionId": "cabin_economy",
                        "cabinType": "ECONOMY",
                        "price": {"total": "940.00", "currency": "CNY"},
                        "availability": "limited",
                        "remainingSeats": 3,
                        "sourceOptionVersion": "mu_5511_y_20260521",
                        "inventoryEvidence": "only 3 left",
                    }
                ],
            }
        ]
    }


def _flight_offer(origin_iata: str, destination_iata: str, day: date, dep_h: int, arr_h: int) -> FlightOffer:
    source = flight_data_source_metadata("airline_mu_public_query", "China Eastern Official Public Flight Query", evidence_id="fixture")
    departure = f"{day.isoformat()}T{dep_h:02d}:00:00+08:00"
    arrival = f"{day.isoformat()}T{arr_h:02d}:00:00+08:00"
    return FlightOffer(
        offer_id=f"{origin_iata}_{destination_iata}_{dep_h}",
        source="PUBLIC_AIRLINE_FIXTURE",
        total_price=money(94000),
        currency="CNY",
        segments=[
            FlightOfferSegment(
                carrier_code="MU",
                flight_number="5511",
                origin_iata=origin_iata,
                destination_iata=destination_iata,
                departure_at=datetime.fromisoformat(departure),
                arrival_at=datetime.fromisoformat(arrival),
                duration=None,
            )
        ],
        validating_airline_codes=["MU"],
        raw_offer={"id": "fixture", "available": True},
        data_source=source,
        cabin_options=[
            FlightOfferCabinOption(
                option_id="cabin_economy",
                cabin_type="ECONOMY",
                price=money(94000),
                availability="AVAILABLE",
                source_option_version="fixture_economy",
                inventory_evidence="fixture_available",
            )
        ],
        evidence_id="fixture",
    )
