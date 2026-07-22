import re
import sqlite3
from datetime import date, datetime

import pytest
import httpx

from app.data_sources.config_loader import DataSourceConfigurationError, load_data_source_settings, reset_data_source_settings_cache
from app.core.context import RequestContext
from app.data_sources.flight_providers import (
    OFFICIAL_AIRLINE_REQUEST_SCHEMAS,
    FlightOffer,
    FlightOfferCabinOption,
    FlightOfferSegment,
    FlightProviderError,
    FlightProviderOutcome,
    FlightProviderSearchResult,
    FlightSearchRequest,
    FlightStateRequest,
    HainanAirlinesPublicQueryProvider,
    OfficialAirlineRequestSchema,
    OfficialAirlinePublicQueryProvider,
    OpenSkyStatesProvider,
    QingdaoAirlinesPublicQueryProvider,
    SpringAirlinesPublicQueryProvider,
    build_enabled_flight_providers,
    flight_data_source_metadata,
    price_flight_offer_with_enabled_provider_result,
    redact_flight_snapshot,
    save_flight_raw_snapshot,
    search_flight_offers_with_enabled_provider_result,
)
from app.models.schemas import (
    LLMValidationResult,
    PlanType,
    RecommendationResult,
    RecommendationSlot,
    RecommendationSlotStatus,
    RecommendationSource,
    RecommendationType,
    TravelHardConstraints,
    TravelRequest,
    TravelSoftPreferences,
    money,
)
from app.services.planner import build_plans, plan_trip


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
        self.responses = list(response) if isinstance(response, list) else [response]
        self.calls = []

    def _next_response(self):
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._next_response()

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._next_response()


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


def test_spring_airlines_provider_posts_public_form_and_maps_real_shape():
    client = _FakeClient(_FakeResponse(_spring_airlines_payload()))
    provider = SpringAirlinesPublicQueryProvider(
        client=client,
        base_url="https://flights.ch.com",
        cache_ttl_seconds=0,
        allowed_hosts=("flights.ch.com",),
        snapshot_backend="disabled",
    )

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="SHA",
            destination_iata="CAN",
            departure_date=date(2026, 7, 23),
            origin_city_name="上海",
            destination_city_name="广州",
            max_results=3,
            non_stop=True,
        )
    )

    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == "https://flights.ch.com/Flights/SearchByTime"
    assert kwargs["data"]["Departure"] == "上海"
    assert kwargs["data"]["Arrival"] == "广州"
    assert kwargs["data"]["DepCityCode"] == "SHA"
    assert kwargs["data"]["ArrCityCode"] == "CAN"
    assert kwargs["data"]["SeatsNum"] == "1"
    assert kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert kwargs["headers"]["Referer"] == "https://flights.ch.com/SHA-CAN.html"
    assert len(offers) == 1
    offer = offers[0]
    assert offer.data_source.source_id == "airline_9c_public_query"
    assert offer.data_source.authority_level == "A"
    assert offer.total_price.amount_minor == 37000
    assert offer.segments[0].carrier_code == "9C"
    assert offer.segments[0].flight_number == "8931"
    assert offer.segments[0].origin_iata == "SHA"
    assert offer.segments[0].destination_iata == "CAN"
    assert offer.cabin_options[0].cabin_type == "经济舱"
    assert offer.cabin_options[0].availability == "AVAILABLE"
    assert offer.cabin_options[0].remaining_count is None
    assert offer.cabin_options[1].availability == "LIMITED"
    assert offer.cabin_options[1].remaining_count == 10


def test_spring_airlines_provider_requires_city_names_without_guessing():
    provider = SpringAirlinesPublicQueryProvider(
        client=_FakeClient(_FakeResponse(_spring_airlines_payload())),
        cache_ttl_seconds=0,
        snapshot_backend="disabled",
    )

    with pytest.raises(FlightProviderError, match="requires origin and destination city names"):
        provider.search_offers(
            FlightSearchRequest(
                origin_iata="SHA",
                destination_iata="CAN",
                departure_date=date(2026, 7, 23),
            )
        )


def test_hainan_airlines_provider_replays_anonymous_session_and_maps_fares():
    client = _FakeClient(
        [
            _FakeResponse(text="<html><form></form></html>", content_type="text/html"),
            _FakeResponse(text="<html>loading</html>", content_type="text/html"),
            _FakeResponse(text=_hainan_airlines_response(), content_type="text/html"),
        ]
    )
    provider = HainanAirlinesPublicQueryProvider(
        client=client,
        cache_ttl_seconds=0,
        snapshot_backend="disabled",
    )

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="BJS",
            destination_iata="SHA",
            departure_date=date(2026, 7, 23),
            max_results=3,
            non_stop=True,
        )
    )

    assert [call[0] for call in client.calls] == ["GET", "POST", "POST"]
    assert client.calls[0][1].endswith("/hainanair/ibe/deeplink/ancillary.do")
    assert client.calls[0][2]["params"]["ORI"] == "BJS"
    assert client.calls[0][2]["params"]["DES"] == "SHA"
    assert client.calls[1][2]["params"]["redirected"] == "true"
    assert client.calls[2][1].endswith("/hainanair/ibe/common/processSearch.do")
    assert len(offers) == 1
    offer = offers[0]
    assert offer.data_source.source_id == "airline_hu_public_query"
    assert offer.total_price.amount_minor == 92000
    assert offer.segments[0].carrier_code == "HU"
    assert offer.segments[0].flight_number == "7601"
    assert offer.segments[0].origin_iata == "PEK"
    assert offer.segments[0].destination_iata == "SHA"
    assert offer.cabin_options[0].cabin_type == "ECONOMY"
    assert offer.cabin_options[0].availability == "AVAILABLE"


def test_qingdao_airlines_provider_derives_anonymous_tokens_and_maps_fares():
    init_payload = {"a": 11, "b": 7, "c": 3, "d": 5, "e": 13, "f": 17, "g": 19}
    client = _FakeClient(
        [
            _FakeResponse(init_payload),
            _FakeResponse(_qingdao_airlines_payload()),
        ]
    )
    provider = QingdaoAirlinesPublicQueryProvider(
        client=client,
        cache_ttl_seconds=0,
        snapshot_backend="disabled",
    )

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="TAO",
            destination_iata="TFU",
            departure_date=date(2026, 7, 20),
            origin_city_name="青岛",
            destination_city_name="成都天府",
            max_results=3,
            non_stop=True,
        )
    )

    assert [call[0] for call in client.calls] == ["GET", "POST"]
    init_cookie_id = client.calls[0][2]["params"]["cookieId"]
    request_body = client.calls[1][2]["json"]
    request_headers = client.calls[1][2]["headers"]
    assert re.fullmatch(r"[0-9a-f]{32}", init_cookie_id)
    assert request_body["openId"] == init_cookie_id
    assert request_body["origCode3"] == "TAO"
    assert request_body["destCode3"] == "TFU"
    assert re.fullmatch(r"[0-9a-f]{32}", request_body["trickToken"])
    assert request_headers["sellerId"] == "B2C"
    assert re.fullmatch(r"[0-9A-F]{32}", request_headers["token"])
    assert len(offers) == 1
    offer = offers[0]
    assert offer.data_source.source_id == "airline_qw_public_query"
    assert offer.total_price.amount_minor == 69900
    assert offer.segments[0].carrier_code == "QW"
    assert offer.segments[0].flight_number == "9771"
    assert offer.cabin_options[0].cabin_type == "ECONOMY"
    assert offer.cabin_options[0].availability == "AVAILABLE"


def test_qingdao_airlines_business_no_flight_message_is_verified_empty():
    client = _FakeClient(
        [
            _FakeResponse({"a": 11, "b": 7, "c": 3, "d": 5, "e": 13, "f": 17, "g": 19}),
            _FakeResponse({"code": 0, "message": "未查询到航班！", "data": None}),
        ]
    )
    provider = QingdaoAirlinesPublicQueryProvider(client=client, cache_ttl_seconds=0, snapshot_backend="disabled")

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="SHA",
            destination_iata="WNZ",
            departure_date=date(2026, 7, 22),
            origin_city_name="上海",
            destination_city_name="温州",
        )
    )

    assert offers == []


def test_unimplemented_public_airline_cannot_be_enabled_through_env(monkeypatch):
    assert [provider.source_id for provider in build_enabled_flight_providers("DEV")] == [
        "airline_9c_public_query",
        "airline_hu_public_query",
        "airline_qw_public_query",
    ]

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
    assert [source.source_id for source in load_data_source_settings().by_adapter("spring_airlines_public_query")] == [
        "airline_9c_public_query"
    ]
    assert [source.source_id for source in load_data_source_settings().by_adapter("hainan_airlines_public_query")] == [
        "airline_hu_public_query"
    ]
    assert [source.source_id for source in load_data_source_settings().by_adapter("qingdao_airlines_public_query")] == [
        "airline_qw_public_query"
    ]


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


def test_flight_search_result_reports_disabled_provider_when_not_configured(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_9C_PUBLIC_QUERY_ENABLED", "false")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_HU_PUBLIC_QUERY_ENABLED", "false")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_QW_PUBLIC_QUERY_ENABLED", "false")
    reset_data_source_settings_cache()
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="WNZ", departure_date=date(2026, 6, 28)),
        environment="DEV",
    )

    assert result.offers == []
    assert result.attempted_source_ids == []
    assert result.failure_message == "no enabled approved official-airline flight provider"
    assert result.outcomes[0].status == "DISABLED"
    assert result.outcomes[0].error_code == "FLIGHT_PROVIDER_DISABLED"


def test_flight_search_result_keeps_each_provider_outcome_and_real_offers(monkeypatch):
    class _Provider:
        def __init__(self, source_id, result):
            self.source_id = source_id
            self.result = result

        def search_offers(self, request):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    day = date(2026, 7, 22)
    offer = _flight_offer("SHA", "WNZ", day, 10, 12)
    providers = [
        _Provider("airline_9c_public_query", FlightProviderError("rate limited (HTTP 429)")),
        _Provider("airline_hu_public_query", []),
        _Provider("airline_qw_public_query", ValueError("invalid response payload")),
        _Provider("airline_mu_browser_query", [offer]),
        _Provider("airline_timeout_query", httpx.ReadTimeout("timed out")),
    ]
    monkeypatch.setattr("app.data_sources.flight_providers.build_enabled_flight_providers", lambda environment=None: providers)

    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="WNZ", departure_date=day),
    )

    assert result.offers == [offer]
    assert [(outcome.source_id, outcome.status, outcome.error_code) for outcome in result.outcomes] == [
        ("airline_9c_public_query", "RATE_LIMITED", "FLIGHT_PROVIDER_RATE_LIMITED"),
        ("airline_hu_public_query", "EMPTY", "FLIGHT_PROVIDER_EMPTY"),
        ("airline_qw_public_query", "FAILED", "FLIGHT_PROVIDER_INVALID_RESPONSE"),
        ("airline_mu_browser_query", "VERIFIED", None),
        ("airline_timeout_query", "TIMEOUT", "FLIGHT_PROVIDER_TIMEOUT"),
    ]


def test_planner_records_flight_outcomes_per_source(monkeypatch):
    def fake_search(request, environment=None):
        return FlightProviderSearchResult(
            offers=[],
            attempted_source_ids=["airline_9c_public_query", "airline_hu_public_query", "airline_qw_public_query"],
            outcomes=[
                FlightProviderOutcome("airline_9c_public_query", "RATE_LIMITED", "FLIGHT_PROVIDER_RATE_LIMITED", True, 0, "HTTP 429"),
                FlightProviderOutcome("airline_hu_public_query", "EMPTY", "FLIGHT_PROVIDER_EMPTY", False, 0, "empty"),
                FlightProviderOutcome("airline_qw_public_query", "FAILED", "FLIGHT_PROVIDER_INVALID_RESPONSE", False, 0, "business code invalid"),
            ],
        )

    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_search)
    request = TravelRequest(
        request_id="req_flight_outcomes",
        raw_user_input="2026-07-22 上海到温州",
        origin_text="上海",
        destination_text="温州",
        travel_date=date(2026, 7, 22),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, _, _, _, _ = build_plans(request)

    assert plans
    failure_pairs = {(failure.source_id, failure.error_code) for failure in failures}
    assert ("airline_9c_public_query", "FLIGHT_PROVIDER_RATE_LIMITED") in failure_pairs
    assert ("airline_hu_public_query", "FLIGHT_PROVIDER_EMPTY") in failure_pairs
    assert ("airline_qw_public_query", "FLIGHT_PROVIDER_INVALID_RESPONSE") in failure_pairs


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        (FlightProviderOutcome("airline_9c_public_query", "RATE_LIMITED", "FLIGHT_PROVIDER_RATE_LIMITED", True, 0, "HTTP 429"), "PARTIAL"),
        (FlightProviderOutcome("airline_hu_public_query", "EMPTY", "FLIGHT_PROVIDER_EMPTY", False, 0, "empty"), "COMPLETE"),
    ],
)
def test_planning_status_distinguishes_unconfirmed_flight_from_verified_empty(monkeypatch, outcome, expected_status):
    monkeypatch.setattr(
        "app.services.planner.search_flight_offers_with_enabled_provider_result",
        lambda request, environment=None: FlightProviderSearchResult(
            offers=[],
            attempted_source_ids=[outcome.source_id],
            outcomes=[outcome],
        ),
    )

    def valid_recommendation(payload):
        plan_id = payload.candidate_plan_ids[0]
        return RecommendationResult(
            recommendation_id="rec_transport_coverage",
            recommendation_source=RecommendationSource.LLM,
            recommendations=[
                RecommendationSlot(recommendation_type=kind, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_id, reason="verified fixture")
                for kind in (RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED)
            ],
            llm_validation_result=LLMValidationResult(
                schema_valid=True,
                semantic_valid=True,
                repair_attempted=False,
                final_strategy="USE_ORIGINAL",
            ),
        )

    monkeypatch.setattr("app.services.planner.recommend_with_validation", valid_recommendation)
    request = TravelRequest(
        request_id="req_transport_coverage",
        raw_user_input="2026-07-22 上海到温州",
        origin_text="上海",
        destination_text="温州",
        travel_date=date(2026, 7, 22),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    response = plan_trip(
        request,
        RequestContext(
            request_id=request.request_id,
            trace_id="trace_transport_coverage",
            correlation_id="corr_transport_coverage",
            idempotency_key="idem_transport_coverage",
        ),
    )

    assert response.planning_status == expected_status
    assert response.plans


def test_planner_does_not_query_or_report_explicitly_excluded_flight(monkeypatch):
    called = False

    def fake_search(request, environment=None):
        nonlocal called
        called = True
        raise AssertionError("flight provider must not be queried")

    monkeypatch.setattr("app.services.planner.search_flight_offers_with_enabled_provider_result", fake_search)
    request = TravelRequest(
        request_id="req_rail_only",
        raw_user_input="2026-07-22 上海到温州，只坐高铁",
        origin_text="上海",
        destination_text="温州",
        travel_date=date(2026, 7, 22),
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(excluded_transport_modes=["FLIGHT"]),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, blocked_types, explanations, _ = build_plans(request)

    assert plans
    assert called is False
    assert "flight_core_fact" not in missing
    assert not any(failure.error_code and failure.error_code.startswith("FLIGHT_PROVIDER") for failure in failures)
    assert not any(plan_type in {PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT} for plan_type in blocked_types)
    assert not any(item.plan_type in {PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT} for item in explanations)


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


def _spring_airlines_payload():
    return {
        "Code": "0",
        "Route": [
            [
                {
                    "No": "9C8931",
                    "SegmentId": "spring_segment_9c8931",
                    "Departure": "上海",
                    "DepartureCode": "SHA",
                    "DepartureAirportCode": "SHA",
                    "DepartureStation": "上海虹桥国际机场T1",
                    "DepartureTime": "2026-07-23 17:35:00",
                    "Arrival": "广州",
                    "ArrivalCode": "CAN",
                    "ArrivalAirportCode": "CAN",
                    "ArrivalStation": "广州白云国际机场T3",
                    "ArrivalTime": "2026-07-23 20:10:00",
                    "FlightTimeM": "2h35m",
                    "Stopovers": [],
                    "AircraftCabins": [
                        {
                            "CabinLevelName": "经济舱",
                            "IsHide": False,
                            "AircraftCabinInfos": [
                                {"Name": "PB", "Price": 370, "Remain": 0},
                                {"Name": "Y1", "Price": 2350, "Remain": 10},
                            ],
                        }
                    ],
                }
            ]
        ],
    }


def _hainan_airlines_response() -> str:
    return """
    <html><script>
    var Flight = {};
    var position = '1';
    var Segment={};
    Segment.marketingAirlineEN = 'HU';
    Segment.marketingFlightNum = '7601';
    Segment.departureDate = '2026-07-23';
    Segment.departureTime = '07:45';
    Segment.departureIATA = 'PEK';
    Segment.departureAirportName = '北京首都国际';
    Segment.arrivalDate = '2026-07-23';
    Segment.arrivalTime = '10:00';
    Segment.arrivalIATA = 'SHA';
    Segment.arrivalAirportName = '上海虹桥';
    Segment.durationHour = '2';
    Segment.durationMin = '15';
    Segment.EquipType = '空客330(宽体)';
    var FareInfo = {};
    FareInfo.resBookDesigCode='R';
    FareInfo.cabinCode='Y';
    FareInfo.fareFamilyName='优惠经济舱';
    priceDetails.baseAmount ='770.0';
    priceDetails.totalAmount ='920.0';
    seatDetails.seatNum ='A';
    FareInfos[FareInfosCode]=FareInfo;
    Flights[position] = Flight;
    </script></html>
    """


def _qingdao_airlines_payload() -> dict:
    return {
        "code": 1,
        "result": {
            "departAVFS": [
                {
                    "flightNo": "QW9771",
                    "flight": "TAO-TFU",
                    "departApCode3": "TAO",
                    "destApCode3": "TFU",
                    "departTime": "08:00",
                    "destTime": "11:05",
                    "minimumPrice": 699,
                    "flightDate": "2026-07-20",
                    "duration": "03:05",
                    "fares": [
                        {
                            "name": "R",
                            "clazzName": "经济舱",
                            "clazzType": "ECO",
                            "price_ad": 699,
                            "avTkt": "A",
                        }
                    ],
                }
            ]
        },
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
