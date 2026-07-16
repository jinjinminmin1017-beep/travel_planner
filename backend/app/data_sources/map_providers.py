from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import ceil
from typing import Any, Literal, Protocol, cast

import httpx

from app.models.schemas import DataSourceMetadata, DataSourceType, GeoPoint, Money, TransportMode, money, now_timepoint

logger = logging.getLogger("app.map")


class MapProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        error_code: str = "MAP_ROUTE_FAILED",
        *,
        field_path: str | None = None,
        actual_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field_path = field_path
        self.actual_type = actual_type


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
    walking_distance_meters: int | None = None


@dataclass(frozen=True)
class MapRouteProviderResult:
    estimate: MapRouteEstimate | None
    attempted_source_ids: list[str]
    failure_message: str | None = None
    fallback_used: bool = False
    fallback_source_id: str | None = None
    fallback_reason: str | None = None
    query_status: Literal["PRIMARY_VERIFIED", "FALLBACK_VERIFIED", "UNAVAILABLE"] = "PRIMARY_VERIFIED"
    error_code: str | None = None


class MapRouteProvider(Protocol):
    source_id: str
    supported_modes: frozenset[TransportMode]

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
        cacheable=True,
    )


class AmapRouteProvider:
    source_id = "amap_route"
    supported_modes = frozenset(
        {
            TransportMode.TAXI,
            TransportMode.RIDE_HAILING,
            TransportMode.RAIL_STATION_TRANSFER,
            TransportMode.AIRPORT_TRANSFER,
            TransportMode.SUBWAY,
            TransportMode.BUS,
            TransportMode.WALK,
        }
    )

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        base_url: str = "https://restapi.amap.com",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout_seconds)
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
                raise MapProviderError("AMap transit response has no transits", "MAP_ROUTE_EMPTY")
            first = transits[0]
            distance = _to_int(first.get("distance"))
            duration = ceil(_to_int(first.get("duration")) / 60)
            cost = _yuan_to_money(first.get("cost"), field_path="route.transits[0].cost")
            return MapRouteEstimate(
                distance,
                duration,
                cost,
                "高德公交/地铁路线规划",
                data_source_metadata(self.source_id, "AMap Route Planning API"),
                walking_distance_meters=_to_optional_int(first.get("walking_distance")),
            )
        paths = route.get("paths") or []
        if not paths:
            raise MapProviderError("AMap route response has no paths", "MAP_ROUTE_EMPTY")
        first = paths[0]
        distance = _to_int(first.get("distance"))
        duration = ceil(_to_int(first.get("duration")) / 60)
        taxi_cost = (
            _yuan_to_money(route.get("taxi_cost"), field_path="route.taxi_cost")
            if request.mode == TransportMode.TAXI
            else None
        )
        return MapRouteEstimate(
            distance,
            duration,
            taxi_cost,
            "高德路线规划",
            data_source_metadata(self.source_id, "AMap Route Planning API"),
            walking_distance_meters=distance if request.mode == TransportMode.WALK else 0,
        )


class BaiduDirectionLiteProvider:
    source_id = "baidu_map_route"
    supported_modes = AmapRouteProvider.supported_modes

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.map.baidu.com",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout_seconds)
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
            raise MapProviderError("Baidu route response has no routes", "MAP_ROUTE_EMPTY")
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
    supported_modes = frozenset(
        {
            TransportMode.TAXI,
            TransportMode.RIDE_HAILING,
            TransportMode.RAIL_STATION_TRANSFER,
            TransportMode.AIRPORT_TRANSFER,
        }
    )

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://router.project-osrm.org",
        timeout_seconds: float = 8.0,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.base_url = base_url.rstrip("/")

    def estimate_route(self, request: MapRouteRequest) -> MapRouteEstimate:
        if request.mode not in self.supported_modes:
            raise MapProviderError(f"OSRM driving does not support {request.mode.value}", "MAP_MODE_UNSUPPORTED")
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
            raise MapProviderError("OSRM route response has no routes", "MAP_ROUTE_EMPTY")
        first = routes[0]
        distance = _to_int(first.get("distance"))
        duration = ceil(_to_int(first.get("duration")) / 60)
        return MapRouteEstimate(
            distance_meters=distance,
            duration_minutes=duration,
            estimated_cost=None,
            summary="OSRM OpenStreetMap 路线规划",
            data_source=data_source_metadata(self.source_id, "OSRM Route Service"),
        )


def build_enabled_map_providers(environment: str | None = None) -> list[MapRouteProvider]:
    from app.data_sources.provider_registry import build_enabled_providers

    return [
        cast(MapRouteProvider, provider)
        for provider in build_enabled_providers(
            {"amap_route", "baidu_map_route", "osrm_route"},
            environment,
        )
    ]


def estimate_route_with_enabled_provider(request: MapRouteRequest, environment: str | None = None) -> MapRouteEstimate | None:
    return estimate_route_with_enabled_provider_result(request, environment).estimate


def estimate_route_with_enabled_provider_result(request: MapRouteRequest, environment: str | None = None) -> MapRouteProviderResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    failure_codes: list[str] = []
    enabled_providers = build_enabled_map_providers(environment)
    compatible_providers = [
        provider
        for provider in enabled_providers
        if request.mode in getattr(provider, "supported_modes", frozenset(TransportMode))
    ]
    for provider in compatible_providers:
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
                query_status="FALLBACK_VERIFIED" if fallback_used else "PRIMARY_VERIFIED",
            )
        except (httpx.HTTPError, MapProviderError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, (ValueError, TypeError, KeyError)):
                exc = MapProviderError(
                    "map provider response has an invalid field structure",
                    "MAP_ROUTE_RESPONSE_INVALID",
                    field_path="unknown",
                    actual_type=type(exc).__name__,
                )
            error_code = _map_error_code(exc)
            if error_code == "MAP_ROUTE_RESPONSE_INVALID":
                logger.warning(
                    "map_provider_response_invalid source_id=%s field_path=%s actual_type=%s error_code=%s",
                    provider.source_id,
                    getattr(exc, "field_path", None) or "unknown",
                    getattr(exc, "actual_type", None) or type(exc).__name__,
                    error_code,
                )
            failure_messages.append(f"{provider.source_id}: {exc}")
            failure_codes.append(error_code)
            continue
    if not enabled_providers:
        error_code = "MAP_ROUTE_NOT_ENABLED"
    elif not compatible_providers:
        error_code = "MAP_MODE_UNSUPPORTED"
    elif failure_codes:
        error_code = _aggregate_failure_code(failure_codes)
    else:
        error_code = "MAP_ROUTE_UNAVAILABLE"
    return MapRouteProviderResult(
        estimate=None,
        attempted_source_ids=attempted_source_ids,
        failure_message="; ".join(failure_messages) or None,
        query_status="UNAVAILABLE",
        error_code=error_code,
    )


def _map_error_code(exc: Exception) -> str:
    if isinstance(exc, MapProviderError):
        return exc.error_code
    if isinstance(exc, httpx.TimeoutException):
        return "MAP_ROUTE_TIMEOUT"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return "MAP_ROUTE_RATE_LIMITED"
    if isinstance(exc, (TypeError, KeyError, ValueError)):
        return "MAP_ROUTE_RESPONSE_INVALID"
    return "MAP_ROUTE_FAILED"


def _aggregate_failure_code(codes: list[str]) -> str:
    priority = [
        "MAP_ROUTE_RATE_LIMITED",
        "MAP_ROUTE_TIMEOUT",
        "MAP_ROUTE_RESPONSE_INVALID",
        "MAP_ROUTE_EMPTY",
        "MAP_ROUTE_FAILED",
    ]
    return next((code for code in priority if code in codes), codes[-1])


def _amap_coord(point: GeoPoint) -> str:
    return f"{point.longitude:.6f},{point.latitude:.6f}"


def _baidu_coord(point: GeoPoint) -> str:
    return f"{point.latitude:.6f},{point.longitude:.6f}"


def _osrm_coord(point: GeoPoint) -> str:
    return f"{point.longitude:.6f},{point.latitude:.6f}"


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(float(value))


def _to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _yuan_to_money(value: Any, *, field_path: str = "cost") -> Money | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        raise _invalid_money_field(field_path, value)
    if isinstance(value, str) and not value.strip():
        return None
    try:
        yuan = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise _invalid_money_field(field_path, value) from None
    if not yuan.is_finite() or yuan < 0:
        raise _invalid_money_field(field_path, value)
    amount_minor = int((yuan * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return money(amount_minor, estimated=True)


def _invalid_money_field(field_path: str, value: Any) -> MapProviderError:
    return MapProviderError(
        f"map provider response field {field_path} has an invalid monetary value",
        "MAP_ROUTE_RESPONSE_INVALID",
        field_path=field_path,
        actual_type=type(value).__name__,
    )
