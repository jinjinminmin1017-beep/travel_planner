from decimal import Decimal

import pytest

from app.core.context import RequestContext
from app.data_sources.config_loader import DataSourceConfigurationError, reset_data_source_settings_cache
from app.data_sources.map_providers import (
    AmapRouteProvider,
    BaiduDirectionLiteProvider,
    MapProviderError,
    MapRouteEstimate,
    MapRouteProviderResult,
    MapRouteRequest,
    OsrmRouteProvider,
    build_enabled_map_providers,
    data_source_metadata,
    estimate_route_with_enabled_provider_result,
    _yuan_to_money,
)
from app.models.schemas import GeoPoint, TransportMode, money
from app.services.intent_parser import parse_travel_request
from app.services.planner import build_plans


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, params))
        return _FakeResponse(self.payload)


def _route_request(mode=TransportMode.TAXI):
    return MapRouteRequest(
        origin=GeoPoint(name="origin", latitude=31.2, longitude=121.3),
        destination=GeoPoint(name="destination", latitude=31.1, longitude=121.4),
        mode=mode,
        origin_city="上海",
        destination_city="上海",
    )


def test_amap_driving_route_maps_real_response():
    client = _FakeClient(
        {
            "status": "1",
            "info": "OK",
            "route": {
                "taxi_cost": "42.5",
                "paths": [{"distance": "18200", "duration": "1960"}],
            },
        }
    )
    provider = AmapRouteProvider("test-key", client=client, base_url="https://example.test")

    estimate = provider.estimate_route(_route_request())

    assert client.calls[0][0] == "https://example.test/v3/direction/driving"
    assert client.calls[0][1]["origin"] == "121.300000,31.200000"
    assert estimate.distance_meters == 18200
    assert estimate.duration_minutes == 33
    assert estimate.estimated_cost.amount_minor == 4250
    assert estimate.data_source.source_id == "amap_route"


def test_amap_transit_route_maps_real_response():
    client = _FakeClient(
        {
            "status": "1",
            "info": "OK",
            "route": {
                "transits": [{"distance": "8600", "duration": "2400", "cost": "5"}],
            },
        }
    )
    provider = AmapRouteProvider("test-key", client=client, base_url="https://example.test")

    estimate = provider.estimate_route(_route_request(TransportMode.SUBWAY))

    assert client.calls[0][0] == "https://example.test/v3/direction/transit/integrated"
    assert client.calls[0][1]["city"] == "上海"
    assert estimate.distance_meters == 8600
    assert estimate.duration_minutes == 40
    assert estimate.estimated_cost.amount_minor == 500


@pytest.mark.parametrize("value", [None, "", "   ", []])
def test_money_parser_preserves_missing_values_as_unknown(value):
    assert _yuan_to_money(value, field_path="route.transits[0].cost") is None


@pytest.mark.parametrize(
    ("value", "expected_amount_minor"),
    [(5, 500), ("5", 500), ("5.25", 525), (Decimal("0.015"), 2)],
)
def test_money_parser_converts_legal_values_with_decimal(value, expected_amount_minor):
    parsed = _yuan_to_money(value, field_path="route.transits[0].cost")

    assert parsed is not None
    assert parsed.amount_minor == expected_amount_minor


@pytest.mark.parametrize("value", [["5"], {}, True, -1, "NaN", "Infinity", "invalid"])
def test_money_parser_rejects_illegal_values_with_structured_error(value):
    with pytest.raises(MapProviderError) as exc_info:
        _yuan_to_money(value, field_path="route.transits[0].cost")

    assert exc_info.value.error_code == "MAP_ROUTE_RESPONSE_INVALID"
    assert exc_info.value.field_path == "route.transits[0].cost"
    assert exc_info.value.actual_type == type(value).__name__


def test_amap_transit_empty_cost_keeps_route_facts_and_unknown_cost():
    client = _FakeClient(
        {
            "status": "1",
            "info": "OK",
            "route": {
                "transits": [
                    {
                        "distance": "8600",
                        "duration": "2400",
                        "cost": [],
                        "walking_distance": "650",
                    }
                ],
            },
        }
    )
    provider = AmapRouteProvider("test-key", client=client, base_url="https://example.test")

    estimate = provider.estimate_route(_route_request(TransportMode.BUS))

    assert estimate.distance_meters == 8600
    assert estimate.duration_minutes == 40
    assert estimate.walking_distance_meters == 650
    assert estimate.estimated_cost is None


def test_dispatcher_returns_structured_invalid_response_without_leaking_payload(monkeypatch, caplog):
    client = _FakeClient(
        {
            "status": "1",
            "route": {
                "transits": [
                    {"distance": "8600", "duration": "2400", "cost": {"secret": "raw-payload-marker"}}
                ]
            },
        }
    )
    provider = AmapRouteProvider("test-key", client=client, base_url="https://example.test")
    monkeypatch.setattr("app.data_sources.map_providers.build_enabled_map_providers", lambda environment=None: [provider])

    result = estimate_route_with_enabled_provider_result(_route_request(TransportMode.SUBWAY), "DEV")

    assert result.estimate is None
    assert result.error_code == "MAP_ROUTE_RESPONSE_INVALID"
    assert result.attempted_source_ids == ["amap_route"]
    assert "raw-payload-marker" not in (result.failure_message or "")
    assert "raw-payload-marker" not in caplog.text
    assert "test-key" not in caplog.text
    assert "field_path=route.transits[0].cost" in caplog.text
    assert "actual_type=dict" in caplog.text


def test_baidu_direction_lite_maps_real_response():
    client = _FakeClient(
        {
            "status": 0,
            "message": "ok",
            "result": {"routes": [{"distance": 5100, "duration": 1260}]},
        }
    )
    provider = BaiduDirectionLiteProvider("test-ak", client=client, base_url="https://example.test")

    estimate = provider.estimate_route(_route_request(TransportMode.WALK))

    assert client.calls[0][0] == "https://example.test/directionlite/v1/walking"
    assert client.calls[0][1]["origin"] == "31.200000,121.300000"
    assert estimate.distance_meters == 5100
    assert estimate.duration_minutes == 21
    assert estimate.estimated_cost is None
    assert estimate.data_source.source_id == "baidu_map_route"


def test_osrm_route_maps_real_response():
    client = _FakeClient(
        {
            "code": "Ok",
            "routes": [
                {
                    "distance": 15474.2,
                    "duration": 986.7,
                }
            ],
        }
    )
    provider = OsrmRouteProvider(client=client, base_url="https://example.test")

    estimate = provider.estimate_route(_route_request())

    assert client.calls[0][0] == "https://example.test/route/v1/driving/121.300000,31.200000;121.400000,31.100000"
    assert client.calls[0][1]["overview"] == "false"
    assert estimate.distance_meters == 15474
    assert estimate.duration_minutes == 17
    assert estimate.estimated_cost is None
    assert estimate.data_source.source_id == "osrm_route"


def test_enabled_map_provider_requires_flag_approved_license_and_key(monkeypatch):
    assert [provider.source_id for provider in build_enabled_map_providers("DEV")] == ["osrm_route"]

    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_QPS_LIMIT", "1")
    reset_data_source_settings_cache()
    with pytest.raises(DataSourceConfigurationError):
        build_enabled_map_providers("DEV")

    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_API_KEY", "test-key")
    reset_data_source_settings_cache()
    assert [provider.source_id for provider in build_enabled_map_providers("DEV")] == ["osrm_route"]

    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_LICENSE_STATUS", "APPROVED")
    reset_data_source_settings_cache()
    providers = build_enabled_map_providers("DEV")
    assert [provider.source_id for provider in providers] == ["amap_route", "osrm_route"]

    monkeypatch.setenv("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_QPS_LIMIT", "1")
    monkeypatch.setenv("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_API_KEY", "test-ak")
    reset_data_source_settings_cache()
    providers = build_enabled_map_providers("DEV")
    assert [provider.source_id for provider in providers] == ["amap_route", "baidu_map_route", "osrm_route"]


def test_map_provider_result_falls_back_in_amap_baidu_osrm_order(monkeypatch):
    class _FailingProvider:
        def __init__(self, source_id):
            self.source_id = source_id

        def estimate_route(self, request):
            raise ValueError(f"{self.source_id} unavailable")

    class _WorkingProvider:
        source_id = "osrm_route"

        def estimate_route(self, request):
            return MapRouteEstimate(
                distance_meters=1200,
                duration_minutes=8,
                estimated_cost=money(1600, estimated=True),
                summary="OSRM fallback route",
                data_source=data_source_metadata("osrm_route", "OSRM Route Service"),
            )

    monkeypatch.setattr(
        "app.data_sources.map_providers.build_enabled_map_providers",
        lambda environment=None: [_FailingProvider("amap_route"), _FailingProvider("baidu_map_route"), _WorkingProvider()],
    )

    result = estimate_route_with_enabled_provider_result(_route_request(), "DEV")

    assert result.estimate is not None
    assert result.estimate.data_source.source_id == "osrm_route"
    assert result.attempted_source_ids == ["amap_route", "baidu_map_route", "osrm_route"]
    assert result.fallback_used is True
    assert result.fallback_source_id == "osrm_route"
    assert "amap_route: map provider response has an invalid field structure" in (result.fallback_reason or "")
    assert "baidu_map_route: map provider response has an invalid field structure" in (result.fallback_reason or "")


def test_map_dispatcher_wraps_type_error_and_continues_fallback(monkeypatch):
    class _BrokenProvider:
        source_id = "amap_route"

        def estimate_route(self, request):
            raise TypeError("raw provider value must not escape")

    class _FallbackProvider:
        source_id = "osrm_route"

        def estimate_route(self, request):
            return MapRouteEstimate(
                distance_meters=1200,
                duration_minutes=8,
                estimated_cost=money(1600, estimated=True),
                summary="OSRM fallback route",
                data_source=data_source_metadata("osrm_route", "OSRM Route Service"),
            )

    monkeypatch.setattr(
        "app.data_sources.map_providers.build_enabled_map_providers",
        lambda environment=None: [_BrokenProvider(), _FallbackProvider()],
    )

    result = estimate_route_with_enabled_provider_result(_route_request(), "DEV")

    assert result.estimate is not None
    assert result.estimate.data_source.source_id == "osrm_route"
    assert result.fallback_used is True
    assert result.attempted_source_ids == ["amap_route", "osrm_route"]
    assert "raw provider value" not in (result.fallback_reason or "")


def test_osrm_driving_is_not_dispatched_for_transit_modes(monkeypatch):
    provider = OsrmRouteProvider(client=_FakeClient({"code": "Ok", "routes": [{"distance": 1200, "duration": 480}]}), base_url="https://example.test")
    monkeypatch.setattr("app.data_sources.map_providers.build_enabled_map_providers", lambda environment=None: [provider])

    request = _route_request()
    request = MapRouteRequest(
        origin=request.origin,
        destination=request.destination,
        mode=TransportMode.SUBWAY,
        origin_city=request.origin_city,
        destination_city=request.destination_city,
    )
    result = estimate_route_with_enabled_provider_result(request, "DEV")

    assert result.estimate is None
    assert result.attempted_source_ids == []
    assert result.error_code == "MAP_MODE_UNSUPPORTED"


def test_planner_uses_real_map_estimate_when_provider_is_enabled(monkeypatch):
    def fake_estimate(request, environment=None):
        estimate = MapRouteEstimate(
            distance_meters=12345,
            duration_minutes=17,
            estimated_cost=money(3300, estimated=True),
            summary="高德测试路线规划",
            data_source=data_source_metadata("amap_route", "AMap Route Planning API"),
        )
        return MapRouteProviderResult(estimate=estimate, attempted_source_ids=["amap_route"])

    monkeypatch.setattr("app.services.planner.estimate_route_with_enabled_provider_result", fake_estimate)
    ctx = RequestContext("req_map", "trace_map", "corr_map", "idem_map")
    travel_request = parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服的方式。",
        ctx,
    )

    plans, *_ = build_plans(travel_request)
    rail_direct = next(plan for plan in plans if plan.plan_id.startswith("plan_rail_direct_dynamic"))
    first_transfer = rail_direct.segments[0]

    assert first_transfer.data_source.source_id == "amap_route"
    assert first_transfer.estimated_cost.amount_minor == 3300
    assert first_transfer.duration_minutes == 17
    assert "高德测试路线规划" in first_transfer.transfer_options[0].ride_instruction
