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
    build_enabled_flight_state_providers,
    flight_data_source_metadata,
)
from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences, money
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


def test_planner_uses_real_flight_offer_when_provider_returns_data(monkeypatch):
    real_source = flight_data_source_metadata("amadeus_flight_offers", "Amadeus Flight Offers Search API")

    def fake_search(request, environment=None):
        assert request.origin_iata == "SHA"
        assert request.destination_iata == "TAO"
        assert request.non_stop is True
        return FlightProviderSearchResult(offers=[
            FlightOffer(
                offer_id="real_1",
                source="GDS",
                total_price=money(88800),
                currency="CNY",
                segments=[
                    FlightOfferSegment(
                        carrier_code="MU",
                        flight_number="5511",
                        origin_iata="SHA",
                        destination_iata="TAO",
                        departure_at=datetime(2026, 5, 21, 12, 10),
                        arrival_at=datetime(2026, 5, 21, 13, 40),
                        duration="PT1H30M",
                    )
                ],
                validating_airline_codes=["MU"],
                raw_offer={"id": "real_1"},
                data_source=real_source,
            )
        ], attempted_source_ids=["amadeus_flight_offers"])

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

    plans, *_ = build_plans(request)
    flight_plan = next(plan for plan in plans if plan.plan_id == "plan_flight_direct_shqd")
    flight_segment = next(segment for segment in flight_plan.segments if getattr(segment, "segment_type", None) == "FLIGHT")

    assert flight_segment.data_source.source_id == "amadeus_flight_offers"
    assert flight_segment.cabin_options[0].price.amount_minor == 88800
    assert flight_segment.duration_minutes == 90
    assert any(source.source_id == "amadeus_flight_offers" for source in flight_plan.data_sources)


def test_planner_does_not_fallback_to_simulated_data_when_real_flight_provider_is_empty(monkeypatch):
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

    try:
        build_plans(request)
    except ValueError as exc:
        assert "real flight provider unavailable" in str(exc)
        assert "empty real response" in str(exc)
    else:
        raise AssertionError("planner must not create a simulated flight when the real provider returns no offers")


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
