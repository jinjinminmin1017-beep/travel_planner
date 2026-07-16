import sqlite3
from datetime import date, datetime

import pytest

from app.data_sources.config_loader import DataSourceConfigurationError, load_data_source_settings, reset_data_source_settings_cache
from app.data_sources.flight_providers import (
    OFFICIAL_AIRLINE_REQUEST_SCHEMAS,
    FlightOffer,
    FlightOfferCabinOption,
    FlightOfferSegment,
    FlightProviderError,
    FlightProviderSearchResult,
    FlightSearchRequest,
    FlightStateRequest,
    OfficialAirlineRequestSchema,
    OfficialAirlinePublicQueryProvider,
    OpenSkyStatesProvider,
    build_enabled_flight_providers,
    flight_data_source_metadata,
    price_flight_offer_with_enabled_provider_result,
    redact_flight_snapshot,
    save_flight_raw_snapshot,
    search_flight_offers_with_enabled_provider_result,
)
from app.models.schemas import PlanType, RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences, money
from app.services.planner import build_plans


class _FakeResponse:
    def __init__(self, payload=None, *, text: str | None = None, content_type: str = "application/json", status_code: int = 200, headers: dict | None = None):
        self.payload = payload
        self.text = text if text is not None else ""
        self.headers = {"content-type": content_type, **(headers or {})}
        self.status_code = status_code

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


def test_official_airline_public_provider_maps_available_cabin_offer():
    client = _FakeClient(_FakeResponse(_public_offer_payload()))
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU", "FM"),
        client=client,
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
        request_schema=_test_schema(),
        snapshot_backend="disabled",
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


def test_official_airline_public_provider_reads_html_embedded_payload():
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
        request_schema=_test_schema(),
        snapshot_backend="disabled",
    )

    offers = provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))

    assert len(offers) == 1
    assert offers[0].offer_id == "mu_html"
    assert offers[0].cabin_options[0].availability == "AVAILABLE"


def test_public_airline_provider_filters_sold_out_and_missing_price():
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
        request_schema=_test_schema(),
        snapshot_backend="disabled",
    )

    offers = provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))

    assert offers == []


def test_public_airline_provider_rejects_base_url_outside_allowlist():
    provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=_FakeClient(_FakeResponse(_public_offer_payload())),
        base_url="https://example.test",
        cache_ttl_seconds=0,
        request_schema=_test_schema(),
        snapshot_backend="disabled",
    )

    with pytest.raises(FlightProviderError, match="outside the source allowlist"):
        provider.search_offers(FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21)))


def test_unimplemented_public_airline_cannot_be_enabled_through_env(monkeypatch):
    assert build_enabled_flight_providers("DEV") == []

    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_QPS_LIMIT", "1")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_SEARCH_PATH", "/api/flight/search")
    reset_data_source_settings_cache()

    with pytest.raises(DataSourceConfigurationError, match="unknown data source configuration keys"):
        load_data_source_settings("DEV")


def test_official_airline_implementation_registry_is_program_owned_and_fail_closed():
    assert OFFICIAL_AIRLINE_REQUEST_SCHEMAS == {}
    assert load_data_source_settings().by_adapter("official_airline_public_query") == ()


def test_public_airline_provider_blocks_captcha_and_rate_limit():
    request = FlightSearchRequest(origin_iata="SHA", destination_iata="TAO", departure_date=date(2026, 5, 21))
    captcha_provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=_FakeClient(_FakeResponse(text="<html>captcha challenge</html>", content_type="text/html")),
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
        request_schema=_test_schema(),
        snapshot_backend="disabled",
    )
    limited_provider = OfficialAirlinePublicQueryProvider(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        allowed_carriers=("MU",),
        client=_FakeClient(_FakeResponse(status_code=429, headers={"retry-after": "60"})),
        base_url="https://example.test",
        cache_ttl_seconds=0,
        allowed_hosts=("example.test",),
        request_schema=_test_schema(),
        snapshot_backend="disabled",
    )

    with pytest.raises(FlightProviderError, match="anti-bot challenge detected"):
        captcha_provider.search_offers(request)
    with pytest.raises(FlightProviderError, match="rate limited .*retry-after=60"):
        limited_provider.search_offers(request)


def test_flight_snapshot_is_redacted_and_request_key_is_fingerprinted(tmp_path):
    snapshot_path = tmp_path / "flight.sqlite3"
    payload = '{"price":433.70,"token":"secret-token","nested":{"sessionId":"abc"},"url":"https://example.test/search?enc=dynamic-secret&route=SHA-TAO"}'

    save_flight_raw_snapshot(
        source_id="airline_cz_public_query",
        request_key="route:SHA:TAO:2026-07-20",
        payload_text=payload,
        content_type="application/json",
        snapshot_path=snapshot_path,
    )

    with sqlite3.connect(snapshot_path) as conn:
        stored_key, stored_payload = conn.execute("SELECT request_key, payload_text FROM flight_raw_snapshots").fetchone()
    assert stored_key.startswith("sha256:")
    assert "SHA:TAO" not in stored_key
    assert "secret-token" not in stored_payload
    assert "dynamic-secret" not in stored_payload
    assert stored_payload.count("[REDACTED]") == 3
    assert "433.7" in stored_payload


def test_redact_flight_snapshot_handles_headers_and_query_tokens():
    redacted = redact_flight_snapshot("Authorization: Bearer top-secret\nCookie: sid=abc\nhttps://example.test/x?enc=xyz&route=SHA-TAO")

    assert "top-secret" not in redacted
    assert "sid=abc" not in redacted
    assert "enc=xyz" not in redacted
    assert "route=SHA-TAO" in redacted


def test_flight_search_result_reports_disabled_provider_when_not_configured():
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="WNZ", departure_date=date(2026, 6, 28)),
        environment="DEV",
    )

    assert result.offers == []
    assert result.attempted_source_ids == []
    assert result.failure_message == "no enabled official-airline flight provider implementation"


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


def _test_schema() -> OfficialAirlineRequestSchema:
    return OfficialAirlineRequestSchema(
        endpoint_method="GET",
        endpoint_path="/api/flight/search",
        query_parameter_names=(
            ("origin_iata", "origin"),
            ("destination_iata", "destination"),
            ("departure_date", "departureDate"),
            ("adults", "adults"),
            ("currency_code", "currency"),
            ("non_stop", "nonStop"),
        ),
    )


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
