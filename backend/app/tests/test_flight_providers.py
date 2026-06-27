from datetime import date, datetime

from app.data_sources.flight_providers import (
    AmadeusFlightProvider,
    FlightOffer,
    FlightProviderSearchResult,
    FlightOfferSegment,
    FlightSearchRequest,
    FlightStateRequest,
    OpenSkyStatesProvider,
    build_enabled_flight_providers,
    build_enabled_flight_price_providers,
    build_enabled_flight_state_providers,
    flight_data_source_metadata,
    price_flight_offer_with_enabled_provider_result,
    search_flight_offers_with_enabled_provider_result,
)
from app.models.schemas import PlanType, RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences, money
from app.services.planner import build_plans


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("/v1/security/oauth2/token"):
            return _FakeResponse({"access_token": "token_test", "token_type": "Bearer"})
        if url.endswith("/v1/shopping/flight-offers/pricing"):
            return _FakeResponse({"data": {"flightOffers": [_amadeus_offer("2", "1088.20")]}})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/v2/shopping/flight-offers"):
            return _FakeResponse({"data": [_amadeus_offer("1", "940.00")]})
        raise AssertionError(f"unexpected GET {url}")


def test_amadeus_search_uses_oauth_and_maps_offers():
    client = _FakeClient()
    provider = AmadeusFlightProvider("client_id", "client_secret", client=client, base_url="https://example.test")

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="SHA",
            destination_iata="TAO",
            departure_date=date(2026, 5, 21),
            adults=1,
            currency_code="CNY",
            max_results=3,
            non_stop=True,
        )
    )

    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "https://example.test/v1/security/oauth2/token"
    assert client.calls[1][0] == "GET"
    assert client.calls[1][1] == "https://example.test/v2/shopping/flight-offers"
    assert client.calls[1][2]["headers"]["Authorization"] == "Bearer token_test"
    assert client.calls[1][2]["params"]["originLocationCode"] == "SHA"
    assert client.calls[1][2]["params"]["destinationLocationCode"] == "TAO"
    assert client.calls[1][2]["params"]["nonStop"] == "true"

    offer = offers[0]
    assert offer.offer_id == "1"
    assert offer.total_price.amount_minor == 94000
    assert offer.total_price.currency == "CNY"
    assert offer.data_source.source_id == "amadeus_flight_offers"
    assert offer.segments[0].carrier_code == "MU"
    assert offer.segments[0].flight_number == "5511"
    assert offer.segments[0].origin_iata == "SHA"
    assert offer.segments[0].destination_iata == "TAO"


def test_amadeus_price_offer_maps_confirmed_price():
    client = _FakeClient()
    provider = AmadeusFlightProvider("client_id", "client_secret", client=client, base_url="https://example.test")

    priced = provider.price_offer(_amadeus_offer("1", "940.00"))

    assert client.calls[1][0] == "POST"
    assert client.calls[1][1] == "https://example.test/v1/shopping/flight-offers/pricing"
    assert client.calls[1][2]["json"]["data"]["type"] == "flight-offers-pricing"
    assert priced.offer_id == "2"
    assert priced.total_price.amount_minor == 108820
    assert priced.data_source.source_id == "amadeus_flight_price"


def test_enabled_amadeus_provider_requires_flag_approval_and_secret_pair(monkeypatch):
    assert build_enabled_flight_providers("DEV") == []

    monkeypatch.setenv("TRAVEL_SOURCE_AMADEUS_FLIGHT_OFFERS_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AMADEUS_FLIGHT_OFFERS_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "client_id")
    assert build_enabled_flight_providers("DEV") == []

    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "client_secret")
    monkeypatch.setenv("AMADEUS_BASE_URL", "https://api.amadeus.com")
    providers = build_enabled_flight_providers("DEV")
    assert [provider.source_id for provider in providers] == ["amadeus_flight_offers"]
    assert providers[0].base_url == "https://api.amadeus.com"


def test_flight_search_result_reports_disabled_provider_when_not_configured():
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(origin_iata="SHA", destination_iata="WNZ", departure_date=date(2026, 6, 28)),
        environment="DEV",
    )

    assert result.offers == []
    assert result.attempted_source_ids == ["amadeus_flight_offers"]
    assert result.failure_message == "no enabled flight offer provider"


def test_enabled_amadeus_price_provider_requires_price_flag_and_secret_pair(monkeypatch):
    assert build_enabled_flight_price_providers("DEV") == []

    monkeypatch.setenv("TRAVEL_SOURCE_AMADEUS_FLIGHT_PRICE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AMADEUS_FLIGHT_PRICE_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "client_id")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "client_secret")
    providers = build_enabled_flight_price_providers("DEV")

    assert [provider.source_id for provider in providers] == ["amadeus_flight_offers"]


def test_price_wrapper_confirms_offer_with_enabled_price_provider(monkeypatch):
    class _PriceProvider:
        def price_offer(self, offer):
            return FlightOffer(
                offer_id="priced_1",
                source="GDS",
                total_price=money(99000),
                currency="CNY",
                segments=[],
                validating_airline_codes=["MU"],
                raw_offer=offer,
                data_source=flight_data_source_metadata("amadeus_flight_price", "Amadeus Flight Offers Price API"),
            )

    monkeypatch.setattr("app.data_sources.flight_providers.build_enabled_flight_price_providers", lambda environment=None: [_PriceProvider()])
    offer = FlightOffer(
        offer_id="offer_1",
        source="GDS",
        total_price=money(94000),
        currency="CNY",
        segments=[],
        validating_airline_codes=["MU"],
        raw_offer={"id": "offer_1"},
        data_source=flight_data_source_metadata("amadeus_flight_offers", "Amadeus Flight Offers Search API"),
    )

    result = price_flight_offer_with_enabled_provider_result(offer)

    assert result.offer.offer_id == "priced_1"
    assert result.offer.total_price.amount_minor == 99000
    assert result.offer.data_source.source_id == "amadeus_flight_price"


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
    providers = build_enabled_flight_state_providers("DEV")
    assert [provider.source_id for provider in providers] == ["opensky_states"]


def test_planner_runtime_no_longer_generates_legacy_flight_templates(monkeypatch):
    called = False

    def fake_search(request, environment=None):
        nonlocal called
        called = True
        return FlightProviderSearchResult(offers=[], attempted_source_ids=["amadeus_flight_offers"], failure_message="should not be called")

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
    assert any(failure.source_id == "amadeus_flight_offers" for failure in failures)
    assert PlanType.DIRECT_FLIGHT in blocked_types
    assert any(item.plan_type == PlanType.DIRECT_FLIGHT and item.reason_code == "CORE_FACT_UNAVAILABLE" for item in explanations)


def test_planner_blocks_flight_plans_when_real_flight_provider_is_empty(monkeypatch):
    def fake_empty_search(request, environment=None):
        return FlightProviderSearchResult(offers=[], attempted_source_ids=["amadeus_flight_offers"], failure_message="empty real response")

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
    assert any(failure.source_id == "amadeus_flight_offers" for failure in failures)


def _amadeus_offer(offer_id: str, total: str):
    return {
        "type": "flight-offer",
        "id": offer_id,
        "source": "GDS",
        "validatingAirlineCodes": ["MU"],
        "price": {"currency": "CNY", "total": total, "grandTotal": total},
        "itineraries": [
            {
                "duration": "PT1H40M",
                "segments": [
                    {
                        "carrierCode": "MU",
                        "number": "5511",
                        "duration": "PT1H40M",
                        "departure": {"iataCode": "SHA", "at": "2026-05-21T11:20:00"},
                        "arrival": {"iataCode": "TAO", "at": "2026-05-21T13:00:00"},
                    }
                ],
            }
        ],
    }
