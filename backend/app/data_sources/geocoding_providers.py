from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, GeoPoint, now_timepoint


class GeocodingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeocodeRequest:
    query: str
    limit: int = 1
    country_codes: str | None = None
    language: str = "zh-CN,zh,en"


@dataclass(frozen=True)
class GeocodeCandidate:
    place_id: str
    display_name: str
    point: GeoPoint
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


class GeocodingProvider(Protocol):
    source_id: str

    def geocode(self, request: GeocodeRequest) -> list[GeocodeCandidate]:
        ...


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
        return GeocodeCandidate(
            place_id=str(item.get("place_id") or ""),
            display_name=str(item.get("display_name") or ""),
            point=GeoPoint(latitude=float(lat), longitude=float(lon)),
            category=_optional_str(item.get("category")),
            place_type=_optional_str(item.get("type")),
            importance=_optional_float(item.get("importance")),
            osm_type=_optional_str(item.get("osm_type")),
            osm_id=_optional_str(item.get("osm_id")),
            data_source=geocoding_data_source_metadata(self.source_id, "Nominatim Search API"),
        )


def geocoding_data_source_metadata(source_id: str, source_name: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.MAP,
        authority_level="B",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        update_frequency="REALTIME_API",
        cacheable=True,
    )


def build_enabled_geocoding_providers(environment: str | None = None) -> list[GeocodingProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("nominatim_geocode")
    if config and config.enabled and config.license_status == "APPROVED":
        return [NominatimGeocodingProvider()]
    return []


def geocode_with_enabled_provider_result(request: GeocodeRequest, environment: str | None = None) -> GeocodeProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_geocoding_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            candidates = provider.geocode(request)
            if candidates:
                return GeocodeProviderSearchResult(candidates=candidates, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
        except (httpx.HTTPError, GeocodingProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
    return GeocodeProviderSearchResult(candidates=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
