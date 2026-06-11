from datetime import date

from app.data_sources.rail_providers import (
    IRailConnectionsProvider,
    RailConnectionRequest,
    RailProviderSearchResult,
    build_enabled_rail_connection_providers,
    search_rail_connections_with_enabled_provider_result,
)
from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeIRailClient:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _irail_connections_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_irail_connections_maps_real_response():
    client = _FakeIRailClient()
    provider = IRailConnectionsProvider(client=client, base_url="https://example.test", user_agent="test-app/1.0")

    connections = provider.search_connections(
        RailConnectionRequest(
            origin_station="Brussels-South",
            destination_station="Gent-Sint-Pieters",
            departure_date=date(2026, 6, 4),
            departure_time="1200",
            results=1,
        )
    )

    assert client.calls[0][0] == "https://example.test/connections/"
    assert client.calls[0][1]["headers"]["User-Agent"] == "test-app/1.0"
    assert client.calls[0][1]["params"]["from"] == "Brussels-South"
    assert client.calls[0][1]["params"]["to"] == "Gent-Sint-Pieters"
    assert client.calls[0][1]["params"]["date"] == "040626"
    assert client.calls[0][1]["params"]["time"] == "1200"
    assert client.calls[0][1]["params"]["format"] == "json"

    connection = connections[0]
    assert connection.connection_id == "0"
    assert connection.train_number == "IC 1526"
    assert connection.origin_station == "Brussels-South/Brussels-Midi"
    assert connection.destination_station == "Ghent-Sint-Pieters"
    assert connection.duration_minutes == 28
    assert connection.transfer_count == 0
    assert connection.platforms == ["12"]
    assert connection.vehicles == ["IC 1526"]
    assert connection.occupancy == "low"
    assert connection.canceled is False
    assert connection.data_source.source_id == "irail_connections"


def test_irail_connection_provider_is_enabled_by_default():
    providers = build_enabled_rail_connection_providers("DEV")
    assert [provider.source_id for provider in providers] == ["irail_connections"]


def test_irail_empty_response_reports_failure_without_fake_connection(monkeypatch):
    class _EmptyProvider:
        source_id = "irail_connections"

        def search_connections(self, request):
            return []

    monkeypatch.setattr("app.data_sources.rail_providers.build_enabled_rail_connection_providers", lambda environment=None: [_EmptyProvider()])

    result = search_rail_connections_with_enabled_provider_result(
        RailConnectionRequest(origin_station="Brussels-South", destination_station="Gent-Sint-Pieters"),
        "DEV",
    )

    assert result.connections == []
    assert result.attempted_source_ids == ["irail_connections"]
    assert result.failure_message == "irail_connections: empty response"


def test_planner_does_not_fallback_to_simulated_data_when_real_rail_provider_is_empty(monkeypatch):
    def fake_empty_search(request, environment=None):
        return RailProviderSearchResult(offers=[], attempted_source_ids=["rail_authorized_partner"], failure_message="empty real response")

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_empty_search)
    request = TravelRequest(
        request_id="req_no_simulated_rail_fallback",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    try:
        build_plans(request)
    except ValueError as exc:
        assert "real rail provider unavailable" in str(exc)
        assert "empty real response" in str(exc)
    else:
        raise AssertionError("planner must not create a simulated rail plan when the real provider returns no offers")


def _irail_connections_payload():
    return {
        "version": "1.4",
        "timestamp": "1780531713",
        "connection": [
            {
                "id": "0",
                "departure": {
                    "station": "Brussels-South/Brussels-Midi",
                    "time": "1780543740",
                    "vehicle": "BE.NMBS.IC1526",
                    "vehicleinfo": {"shortname": "IC 1526", "number": "1526"},
                    "platform": "12",
                    "canceled": "0",
                    "occupancy": {"name": "low"},
                },
                "arrival": {
                    "station": "Ghent-Sint-Pieters",
                    "time": "1780545420",
                    "vehicle": "BE.NMBS.IC1526",
                    "vehicleinfo": {"shortname": "IC 1526", "number": "1526"},
                    "platform": "12",
                    "canceled": "0",
                },
                "duration": "1680",
                "vias": {"number": "0", "via": []},
            }
        ],
    }
