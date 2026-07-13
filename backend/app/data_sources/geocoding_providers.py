from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, GeoPoint, now_timepoint


class GeocodingProviderError(RuntimeError):
    def __init__(self, message: str, error_code: str = "MAP_GEOCODING_FAILED") -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class GeocodeRequest:
    query: str
    limit: int = 1
    city: str | None = None
    country_codes: str | None = None
    language: str = "zh-CN,zh,en"


@dataclass(frozen=True)
class GeocodeCandidate:
    place_id: str
    display_name: str
    point: GeoPoint
    address: dict[str, str]
    category: str | None
    place_type: str | None
    importance: float | None
    osm_type: str | None
    osm_id: str | None
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class GeocodeProviderSearchResult:
    candidates: list[GeocodeCandidate]
    attempted_source_ids: list[str]
    failure_message: str | None = None
    error_code: str | None = None


class GeocodingProvider(Protocol):
    source_id: str

    def geocode(self, request: GeocodeRequest) -> list[GeocodeCandidate]:
        ...


class AmapAddressGeocodingProvider:
    source_id = "amap_geocode"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=5.0)
        self.base_url = (base_url or os.getenv("AMAP_GEOCODING_BASE_URL") or "https://restapi.amap.com").rstrip("/")

    def geocode(self, request: GeocodeRequest) -> list[GeocodeCandidate]:
        if not request.query.strip():
            raise GeocodingProviderError("geocode query is empty")
        params = {
            "key": self.api_key,
            "address": request.query,
            "batch": "false",
            "output": "JSON",
        }
        if request.city:
            params["city"] = request.city
        response = self.client.get(f"{self.base_url}/v3/geocode/geo", params=params)
        response.raise_for_status()
        payload = _amap_payload(response.json(), "AMap address geocoding")
        geocodes = payload.get("geocodes") or []
        if not isinstance(geocodes, list):
            raise GeocodingProviderError("AMap geocodes is not a list")
        return [self._parse_candidate(item) for item in geocodes[: max(1, min(request.limit, 10))]]

    def _parse_candidate(self, item: dict[str, Any]) -> GeocodeCandidate:
        point = _amap_point(item.get("location"), str(item.get("formatted_address") or ""))
        address = _amap_address(
            province=item.get("province"),
            city=item.get("city"),
            district=item.get("district"),
            township=item.get("township"),
            adcode=item.get("adcode"),
        )
        display_name = str(item.get("formatted_address") or point.name)
        return GeocodeCandidate(
            place_id=f"amap-geocode:{item.get('adcode') or display_name}",
            display_name=display_name,
            point=point.model_copy(update={"name": display_name}),
            address=address,
            category=None,
            place_type="address",
            importance=None,
            osm_type=None,
            osm_id=None,
            data_source=geocoding_data_source_metadata(self.source_id, "AMap Address Geocoding API", authority_level="A"),
        )


class AmapPlaceSearchProvider:
    source_id = "amap_place_search"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=5.0)
        self.base_url = (base_url or os.getenv("AMAP_GEOCODING_BASE_URL") or "https://restapi.amap.com").rstrip("/")

    def geocode(self, request: GeocodeRequest) -> list[GeocodeCandidate]:
        if not request.query.strip():
            raise GeocodingProviderError("place-search query is empty")
        params = {
            "key": self.api_key,
            "keywords": request.query,
            "offset": max(1, min(request.limit, 10)),
            "page": 1,
            "extensions": "base",
            "output": "JSON",
        }
        if request.city:
            params["city"] = request.city
            params["citylimit"] = "true"
        response = self.client.get(f"{self.base_url}/v3/place/text", params=params)
        response.raise_for_status()
        payload = _amap_payload(response.json(), "AMap place search")
        pois = payload.get("pois") or []
        if not isinstance(pois, list):
            raise GeocodingProviderError("AMap POIs is not a list")
        return [self._parse_candidate(item) for item in pois]

    def _parse_candidate(self, item: dict[str, Any]) -> GeocodeCandidate:
        name = str(item.get("name") or "")
        address = _amap_address(
            province=item.get("pname"),
            city=item.get("cityname"),
            district=item.get("adname"),
            street=item.get("address"),
            adcode=item.get("adcode"),
        )
        point = _amap_point(item.get("location"), name)
        address_text = str(item.get("address") or "")
        display_name = "，".join(part for part in (name, str(item.get("cityname") or ""), str(item.get("adname") or ""), address_text) if part)
        return GeocodeCandidate(
            place_id=str(item.get("id") or f"amap-poi:{display_name}"),
            display_name=display_name or name,
            point=point.model_copy(update={"name": name or display_name}),
            address=address,
            category=_optional_str(item.get("type")),
            place_type=_optional_str(item.get("typecode")),
            importance=None,
            osm_type=None,
            osm_id=None,
            data_source=geocoding_data_source_metadata(self.source_id, "AMap Place Search API", authority_level="A"),
        )


class NominatimGeocodingProvider:
    source_id = "nominatim_geocode"

    def __init__(self, client: httpx.Client | None = None, base_url: str | None = None, user_agent: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("NOMINATIM_BASE_URL") or "https://nominatim.openstreetmap.org").rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)
        self.user_agent = user_agent or os.getenv("NOMINATIM_USER_AGENT") or "AITravelPlanner/0.1 (local-dev)"

    def geocode(self, request: GeocodeRequest) -> list[GeocodeCandidate]:
        if not request.query.strip():
            raise GeocodingProviderError("geocode query is empty")
        params: dict[str, str | int] = {
            "q": request.query,
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": max(1, min(request.limit, 5)),
        }
        if request.country_codes:
            params["countrycodes"] = request.country_codes
        response = self.client.get(
            f"{self.base_url}/search",
            params=params,
            headers={
                "Accept": "application/json",
                "Accept-Language": request.language,
                "User-Agent": self.user_agent,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise GeocodingProviderError("Nominatim response is not a list")
        return [self._parse_candidate(item) for item in payload]

    def _parse_candidate(self, item: dict[str, Any]) -> GeocodeCandidate:
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            raise GeocodingProviderError("Nominatim result has no coordinates")
        display_name = str(item.get("display_name") or "")
        raw_address = item.get("address") if isinstance(item.get("address"), dict) else {}
        return GeocodeCandidate(
            place_id=str(item.get("place_id") or ""),
            display_name=display_name,
            point=GeoPoint(name=display_name, latitude=float(lat), longitude=float(lon)),
            address={str(key): str(value) for key, value in raw_address.items() if value is not None and value != ""},
            category=_optional_str(item.get("category")),
            place_type=_optional_str(item.get("type")),
            importance=_optional_float(item.get("importance")),
            osm_type=_optional_str(item.get("osm_type")),
            osm_id=_optional_str(item.get("osm_id")),
            data_source=geocoding_data_source_metadata(self.source_id, "Nominatim Search API"),
        )


def geocoding_data_source_metadata(source_id: str, source_name: str, *, authority_level: str = "B") -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.MAP,
        authority_level=authority_level,
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
    )


def build_enabled_geocoding_providers(environment: str | None = None) -> list[GeocodingProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    providers: list[GeocodingProvider] = []
    amap_key = _first_env("AMAP_WEB_SERVICE_KEY", "AMAP_API_KEY")
    amap_geocode = configs.get("amap_geocode")
    if amap_key and amap_geocode and amap_geocode.enabled and amap_geocode.license_status == "APPROVED" and has_required_secret("amap_geocode"):
        providers.append(AmapAddressGeocodingProvider(amap_key))
    amap_place_search = configs.get("amap_place_search")
    if amap_key and amap_place_search and amap_place_search.enabled and amap_place_search.license_status == "APPROVED" and has_required_secret("amap_place_search"):
        providers.append(AmapPlaceSearchProvider(amap_key))
    nominatim = configs.get("nominatim_geocode")
    if nominatim and nominatim.enabled and nominatim.license_status == "APPROVED":
        providers.append(NominatimGeocodingProvider())
    return providers


def geocode_with_enabled_provider_result(request: GeocodeRequest, environment: str | None = None) -> GeocodeProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    failure_codes: list[str] = []
    ambiguous_candidates: list[GeocodeCandidate] = []
    for provider in build_enabled_geocoding_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            candidates = _filter_candidates_for_city(provider.geocode(request), request.city)
            if len(candidates) == 1:
                return GeocodeProviderSearchResult(candidates=candidates, attempted_source_ids=attempted_source_ids)
            if candidates:
                # Prefer AMap POI candidates over broader address/Nominatim
                # matches so the resolver can apply exact-name/address scoring.
                if provider.source_id != "nominatim_geocode" or not ambiguous_candidates:
                    ambiguous_candidates = candidates
                failure_messages.append(f"{provider.source_id}: ambiguous response ({len(candidates)} candidates)")
                failure_codes.append("MAP_LOCATION_AMBIGUOUS")
                continue
            failure_messages.append(f"{provider.source_id}: empty response")
            failure_codes.append("MAP_GEOCODING_EMPTY")
        except (httpx.HTTPError, GeocodingProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
            failure_codes.append(_geocoding_error_code(exc))
    return GeocodeProviderSearchResult(
        candidates=ambiguous_candidates,
        attempted_source_ids=attempted_source_ids,
        failure_message="; ".join(failure_messages) or None,
        error_code="MAP_LOCATION_AMBIGUOUS" if ambiguous_candidates else _aggregate_geocoding_error_code(failure_codes),
    )


def _amap_payload(payload: Any, operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GeocodingProviderError(f"{operation} response is not an object")
    if str(payload.get("status")) != "1":
        info = str(payload.get("info") or payload.get("infocode") or "unknown error")
        code = "MAP_GEOCODING_RATE_LIMITED" if str(payload.get("infocode")) in {"10003", "10004", "10020", "10021"} else "MAP_GEOCODING_FAILED"
        raise GeocodingProviderError(f"{operation} failed: {info}", code)
    return payload


def _amap_point(value: Any, name: str) -> GeoPoint:
    if not isinstance(value, str) or "," not in value:
        raise GeocodingProviderError("AMap result has no coordinates", "MAP_GEOCODING_EMPTY")
    longitude, latitude = value.split(",", 1)
    return GeoPoint(name=name, latitude=float(latitude), longitude=float(longitude))


def _amap_address(**values: Any) -> dict[str, str]:
    address: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, list):
            value = next((item for item in value if item), "")
        if value is not None and value != "":
            address[key] = str(value)
    return address


def _filter_candidates_for_city(candidates: list[GeocodeCandidate], city: str | None) -> list[GeocodeCandidate]:
    if not city:
        return candidates
    normalized_city = _normalize_admin_name(city)
    matched = [
        candidate
        for candidate in candidates
        if normalized_city in {_normalize_admin_name(candidate.address.get(key, "")) for key in ("city", "town", "municipality", "county", "district", "state_district")}
        or normalized_city in _normalize_admin_name(candidate.display_name)
    ]
    return matched


def _normalize_admin_name(value: str) -> str:
    normalized = value.strip().replace(" ", "")
    for suffix in ("特别行政区", "自治区", "省", "市", "地区", "盟", "县", "区"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _geocoding_error_code(exc: Exception) -> str:
    if isinstance(exc, GeocodingProviderError):
        return exc.error_code
    if isinstance(exc, httpx.TimeoutException):
        return "MAP_GEOCODING_TIMEOUT"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return "MAP_GEOCODING_RATE_LIMITED"
    return "MAP_GEOCODING_FAILED"


def _aggregate_geocoding_error_code(codes: list[str]) -> str | None:
    priority = ["MAP_GEOCODING_RATE_LIMITED", "MAP_GEOCODING_TIMEOUT", "MAP_GEOCODING_FAILED", "MAP_GEOCODING_EMPTY"]
    return next((code for code in priority if code in codes), codes[-1] if codes else None)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
