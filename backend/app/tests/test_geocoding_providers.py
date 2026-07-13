from app.data_sources.geocoding_providers import (
    AmapAddressGeocodingProvider,
    AmapPlaceSearchProvider,
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
    assert candidate.address["city"] == "青岛市"
    assert candidate.address["state"] == "山东省"
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


def test_amap_address_geocoding_maps_coordinates_and_city():
    client = _FakeNominatimClient(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "geocodes": [
                {
                    "formatted_address": "浙江省温州市永嘉县桥头镇梨村",
                    "province": "浙江省",
                    "city": "温州市",
                    "district": "永嘉县",
                    "township": "桥头镇",
                    "adcode": "330324",
                    "location": "120.482100,28.168200",
                }
            ],
        }
    )
    provider = AmapAddressGeocodingProvider("test-key", client=client, base_url="https://example.test")

    candidates = provider.geocode(GeocodeRequest(query="温州永嘉桥头梨村", city="温州", limit=5))

    assert client.calls[0][0] == "https://example.test/v3/geocode/geo"
    assert client.calls[0][1]["params"]["address"] == "温州永嘉桥头梨村"
    assert client.calls[0][1]["params"]["city"] == "温州"
    assert candidates[0].point.longitude == 120.4821
    assert candidates[0].address["city"] == "温州市"
    assert candidates[0].data_source.source_id == "amap_geocode"


def test_amap_place_search_uses_city_limit_and_maps_poi():
    client = _FakeNominatimClient(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "pois": [
                {
                    "id": "B001",
                    "name": "武汉新天地",
                    "type": "商务住宅;住宅区",
                    "typecode": "120300",
                    "pname": "湖北省",
                    "cityname": "武汉市",
                    "adname": "江岸区",
                    "address": "卢沟桥路",
                    "adcode": "420102",
                    "location": "114.311500,30.610500",
                }
            ],
        }
    )
    provider = AmapPlaceSearchProvider("test-key", client=client, base_url="https://example.test")

    candidates = provider.geocode(GeocodeRequest(query="武汉新天地", city="武汉", limit=5))

    assert client.calls[0][0] == "https://example.test/v3/place/text"
    assert client.calls[0][1]["params"]["keywords"] == "武汉新天地"
    assert client.calls[0][1]["params"]["citylimit"] == "true"
    assert candidates[0].place_id == "B001"
    assert candidates[0].point.latitude == 30.6105
    assert candidates[0].data_source.source_id == "amap_place_search"


def test_geocoding_chain_uses_poi_search_after_empty_address_result(monkeypatch):
    class _EmptyAddressProvider:
        source_id = "amap_geocode"

        def geocode(self, request):
            return []

    class _WorkingPoiProvider:
        source_id = "amap_place_search"

        def geocode(self, request):
            return AmapPlaceSearchProvider(
                "test-key",
                client=_FakeNominatimClient(
                    {
                        "status": "1",
                        "pois": [
                            {
                                "id": "B002",
                                "name": "武汉新天地",
                                "cityname": "武汉市",
                                "adname": "江岸区",
                                "location": "114.311500,30.610500",
                            }
                        ],
                    }
                ),
                base_url="https://example.test",
            ).geocode(request)

    monkeypatch.setattr(
        "app.data_sources.geocoding_providers.build_enabled_geocoding_providers",
        lambda environment=None: [_EmptyAddressProvider(), _WorkingPoiProvider()],
    )

    result = geocode_with_enabled_provider_result(GeocodeRequest(query="武汉新天地", city="武汉", limit=5), "DEV")

    assert result.candidates[0].data_source.source_id == "amap_place_search"
    assert result.attempted_source_ids == ["amap_geocode", "amap_place_search"]


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
            "address": {
                "attraction": "栈桥",
                "city": "青岛市",
                "state": "山东省",
                "country": "中国",
            },
        }
    ]
