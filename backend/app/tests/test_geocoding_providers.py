from app.data_sources.geocoding_providers import (
    GeocodeRequest,
    NominatimGeocodingProvider,
    build_enabled_geocoding_providers,
    geocode_with_enabled_provider_result,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeNominatimClient:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _nominatim_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_nominatim_geocode_maps_real_response():
    client = _FakeNominatimClient()
    provider = NominatimGeocodingProvider(client=client, base_url="https://example.test", user_agent="test-app/1.0")

    candidates = provider.geocode(GeocodeRequest(query="青岛栈桥", country_codes="cn", limit=1))

    assert client.calls[0][0] == "https://example.test/search"
    assert client.calls[0][1]["headers"]["User-Agent"] == "test-app/1.0"
    assert client.calls[0][1]["headers"]["Accept-Language"] == "zh-CN,zh,en"
    assert client.calls[0][1]["params"]["q"] == "青岛栈桥"
    assert client.calls[0][1]["params"]["countrycodes"] == "cn"
    assert client.calls[0][1]["params"]["format"] == "jsonv2"
    assert client.calls[0][1]["params"]["limit"] == 1

    candidate = candidates[0]
    assert candidate.place_id == "123"
    assert candidate.display_name.startswith("栈桥")
    assert candidate.point.latitude == 36.0611
    assert candidate.point.longitude == 120.3192
    assert candidate.category == "tourism"
    assert candidate.place_type == "attraction"
    assert candidate.importance == 0.7
    assert candidate.osm_type == "way"
    assert candidate.osm_id == "456"
    assert candidate.data_source.source_id == "nominatim_geocode"
    assert candidate.data_source.source_type == "MAP"


def test_nominatim_geocode_provider_is_enabled_by_default():
    providers = build_enabled_geocoding_providers("DEV")
    assert [provider.source_id for provider in providers] == ["nominatim_geocode"]


def test_nominatim_empty_response_reports_failure(monkeypatch):
    class _EmptyProvider:
        source_id = "nominatim_geocode"

        def geocode(self, request):
            return []

    monkeypatch.setattr("app.data_sources.geocoding_providers.build_enabled_geocoding_providers", lambda environment=None: [_EmptyProvider()])

    result = geocode_with_enabled_provider_result(GeocodeRequest(query="not found"), "DEV")

    assert result.candidates == []
    assert result.attempted_source_ids == ["nominatim_geocode"]
    assert result.failure_message == "nominatim_geocode: empty response"


def _nominatim_payload():
    return [
        {
            "place_id": 123,
            "osm_type": "way",
            "osm_id": 456,
            "lat": "36.0611",
            "lon": "120.3192",
            "category": "tourism",
            "type": "attraction",
            "importance": 0.7,
            "display_name": "栈桥, 市南区, 青岛市, 山东省, 中国",
        }
    ]
