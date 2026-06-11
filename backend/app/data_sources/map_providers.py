from __future__ import annotations

import os
from dataclasses import dataclass
from math import ceil
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, GeoPoint, Money, TransportMode, money, now_timepoint


class MapProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class MapRouteRequest:
    origin: GeoPoint
    destination: GeoPoint
    mode: TransportMode
    origin_city: str | None = None
    destination_city: str | None = None


@dataclass(frozen=True)
class MapRouteEstimate:
    distance_meters: int
    duration_minutes: int
    estimated_cost: Money | None
    summary: str
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class MapRouteProviderResult:
    estimate: MapRouteEstimate | None
    attempted_source_ids: list[str]
    failure_message: str | None = None
    fallback_used: bool = False
    fallback_source_id: str | None = None
    fallback_reason: str | None = None


class MapRouteProvider(Protocol):
    source_id: str

    def estimate_route(self, request: MapRouteRequest) -> MapRouteEstimate:
        ...


def data_source_metadata(source_id: str, source_name: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.MAP,
        authority_level="A",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        update_frequency="REALTIME_API",
        cacheable=True,
    )


class AmapRouteProvider:
    source_id = "amap_route"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base_url: str = "https://restapi.amap.com") -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=5.0)
        self.base_url = base_url.rstrip("/")

    def estimate_route(self, request: MapRouteRequest) -> MapRouteEstimate:
        endpoint, params = self._endpoint_and_params(request)
        response = self.client.get(f"{self.base_url}{endpoint}", params=params)
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("status")) != "1":
            raise MapProviderError(f"AMap route failed: {payload.get('info') or payload.get('infocode')}")
        return self._parse_payload(request, payload)

    def _endpoint_and_params(self, request: MapRouteRequest) -> tuple[str, dict[str, str]]:
        origin = _amap_coord(request.origin)
        destination = _amap_coord(request.destination)
        params = {"key": self.api_key, "origin": origin, "destination": destination, "output": "JSON"}
        if request.mode in {TransportMode.TAXI, TransportMode.RAIL_STATION_TRANSFER, TransportMode.AIRPORT_TRANSFER}:
            params["extensions"] = "all"
            return "/v3/direction/driving", params
        if request.mode == TransportMode.WALK:
            return "/v3/direction/walking", params
        if request.mode in {TransportMode.SUBWAY, TransportMode.BUS}:
            if request.origin_city:
                params["city"] = request.origin_city
            if request.destination_city:
                params["cityd"] = request.destination_city
            return "/v3/direction/transit/integrated", params
        return "/v3/direction/driving", params

    def _parse_payload(self, request: MapRouteRequest, payload: dict[str, Any]) -> MapRouteEstimate:
        route = payload.get("route") or {}
        if request.mode in {TransportMode.SUBWAY, TransportMode.BUS}:
            transits = route.get("transits") or []
            if not transits:
                raise MapProviderError("AMap transit response has no transits")
            first = transits[0]
            distance = _to_int(first.get("distance"))
            duration = ceil(_to_int(first.get("duration")) / 60)
            cost = _yuan_to_money(first.get("cost"))
            return MapRouteEstimate(distance, duration, cost, "高德公交/地铁路线规划", data_source_metadata(self.source_id, "AMap Route Planning API"))
        paths = route.get("paths") or []
        if not paths:
            raise MapProviderError("AMap route response has no paths")
        first = paths[0]
        distance = _to_int(first.get("distance"))
        duration = ceil(_to_int(first.get("duration")) / 60)
        taxi_cost = _yuan_to_money(route.get("taxi_cost")) if request.mode == TransportMode.TAXI else None
        return MapRouteEstimate(distance, duration, taxi_cost, "高德路线规划", data_source_metadata(self.source_id, "AMap Route Planning API"))


class BaiduDirectionLiteProvider:
    source_id = "baidu_map_route"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base_url: str = "https://api.map.baidu.com") -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=5.0)
        self.base_url = base_url.rstrip("/")

    def estimate_route(self, request: MapRouteRequest) -> MapRouteEstimate:
        endpoint = self._endpoint(request.mode)
        params = {
            "ak": self.api_key,
            "origin": _baidu_coord(request.origin),
            "destination": _baidu_coord(request.destination),
            "coord_type": "wgs84",
        }
        response = self.client.get(f"{self.base_url}{endpoint}", params=params)
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("status", -1)) != 0:
            raise MapProviderError(f"Baidu route failed: {payload.get('message') or payload.get('status')}")
        routes = (payload.get("result") or {}).get("routes") or []
        if not routes:
            raise MapProviderError("Baidu route response has no routes")
        first = routes[0]
        return MapRouteEstimate(
            distance_meters=_to_int(first.get("distance")),
            duration_minutes=ceil(_to_int(first.get("duration")) / 60),
            estimated_cost=None,
            summary="百度轻量路线规划",
            data_source=data_source_metadata(self.source_id, "Baidu Map Route Planning API"),
        )

    def _endpoint(self, mode: TransportMode) -> str:
        if mode in {TransportMode.SUBWAY, TransportMode.BUS}:
            return "/directionlite/v1/transit"
        if mode == TransportMode.WALK:
            return "/directionlite/v1/walking"
        return "/directionlite/v1/driving"


class OsrmRouteProvider:
    source_id = "osrm_route"

    def __init__(self, client: httpx.Client | None = None, base_url: str | None = None) -> None:
        self.client = client or httpx.Client(timeout=8.0)
        self.base_url = (base_url or os.getenv("OSRM_ROUTE_BASE_URL") or "https://router.project-osrm.org").rstrip("/")

    def estimate_route(self, request: MapRouteRequest) -> MapRouteEstimate:
        params = {"overview": "false", "alternatives": "false", "steps": "false"}
        response = self.client.get(
            f"{self.base_url}/route/v1/driving/{_osrm_coord(request.origin)};{_osrm_coord(request.destination)}",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "Ok":
            raise MapProviderError(f"OSRM route failed: {payload.get('code')}")
        routes = payload.get("routes") or []
        if not routes:
            raise MapProviderError("OSRM route response has no routes")
        first = routes[0]
        distance = _to_int(first.get("distance"))
        duration = ceil(_to_int(first.get("duration")) / 60)
        return MapRouteEstimate(
            distance_meters=distance,
            duration_minutes=duration,
            estimated_cost=_estimated_transfer_cost(request.mode, distance),
            summary="OSRM OpenStreetMap 路线规划",
            data_source=data_source_metadata(self.source_id, "OSRM Route Service"),
        )


def build_enabled_map_providers(environment: str | None = None) -> list[MapRouteProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    providers: list[MapRouteProvider] = []
    amap_config = configs.get("amap_route")
    if amap_config and amap_config.enabled and amap_config.license_status == "APPROVED" and has_required_secret("amap_route"):
        providers.append(AmapRouteProvider(_first_env("AMAP_WEB_SERVICE_KEY", "AMAP_API_KEY")))
    baidu_config = configs.get("baidu_map_route")
    if baidu_config and baidu_config.enabled and baidu_config.license_status == "APPROVED" and has_required_secret("baidu_map_route"):
        providers.append(BaiduDirectionLiteProvider(_first_env("BAIDU_MAP_AK", "BAIDU_MAP_API_KEY")))
    osrm_config = configs.get("osrm_route")
    if osrm_config and osrm_config.enabled and osrm_config.license_status == "APPROVED":
        providers.append(OsrmRouteProvider())
    return providers


def estimate_route_with_enabled_provider(request: MapRouteRequest, environment: str | None = None) -> MapRouteEstimate | None:
    return estimate_route_with_enabled_provider_result(request, environment).estimate


def estimate_route_with_enabled_provider_result(request: MapRouteRequest, environment: str | None = None) -> MapRouteProviderResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_map_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            estimate = provider.estimate_route(request)
            fallback_used = len(attempted_source_ids) > 1
            return MapRouteProviderResult(
                estimate=estimate,
                attempted_source_ids=attempted_source_ids,
                fallback_used=fallback_used,
                fallback_source_id=provider.source_id if fallback_used else None,
                fallback_reason="; ".join(failure_messages) if fallback_used else None,
            )
        except (httpx.HTTPError, MapProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
            continue
    return MapRouteProviderResult(
        estimate=None,
        attempted_source_ids=attempted_source_ids,
        failure_message="; ".join(failure_messages) or None,
    )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise MapProviderError(f"missing API credential env: {'/'.join(names)}")


def _amap_coord(point: GeoPoint) -> str:
    return f"{point.longitude:.6f},{point.latitude:.6f}"


def _baidu_coord(point: GeoPoint) -> str:
    return f"{point.latitude:.6f},{point.longitude:.6f}"


def _osrm_coord(point: GeoPoint) -> str:
    return f"{point.longitude:.6f},{point.latitude:.6f}"


def _estimated_transfer_cost(mode: TransportMode, distance_meters: int) -> Money | None:
    if mode in {TransportMode.TAXI, TransportMode.RAIL_STATION_TRANSFER, TransportMode.AIRPORT_TRANSFER}:
        return money(max(1400, int(round(1400 + distance_meters * 2.4))), estimated=True)
    if mode == TransportMode.SUBWAY:
        return money(max(300, min(1200, int(round(distance_meters / 5000)) * 100 + 300)), estimated=True)
    if mode == TransportMode.BUS:
        return money(200 if distance_meters < 12000 else 400, estimated=True)
    return None


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(float(value))


def _yuan_to_money(value: Any) -> Money | None:
    if value is None or value == "":
        return None
    return money(int(round(float(value) * 100)), estimated=True)
