from __future__ import annotations

import html
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.models.schemas import CacheMetadata, DataSourceMetadata, DataSourceType, Money, money, now_timepoint

logger = logging.getLogger("app.flight")


class FlightProviderError(RuntimeError):
    pass


class FlightParserRejectedAllError(FlightProviderError):
    """The upstream returned candidates, but none passed deterministic parsing."""


FlightQueryScope = Literal["CITY", "AIRPORT"]


@dataclass(frozen=True)
class FlightSearchScope:
    origin_city_name: str
    destination_city_name: str
    origin_city_code: str
    destination_city_code: str
    allowed_origin_airport_iatas: tuple[str, ...]
    allowed_destination_airport_iatas: tuple[str, ...]
    departure_date: date
    adults: int = 1
    currency_code: str = "CNY"
    max_results: int = 5
    non_stop: bool | None = None

    @property
    def origin_iata(self) -> str:
        """Compatibility view for existing planner diagnostics and test doubles."""
        return self.origin_city_code

    @property
    def destination_iata(self) -> str:
        return self.destination_city_code


@dataclass(frozen=True)
class OfficialAirlineRequestSchema:
    """Program-owned request mapping for a verified official-airline adapter."""

    endpoint_method: Literal["GET"]
    endpoint_path: str
    query_parameter_names: tuple[tuple[str, str], ...]

    def request_params(self, values: dict[str, object]) -> dict[str, object]:
        mapping = dict(self.query_parameter_names)
        return {wire_name: values[field_name] for field_name, wire_name in mapping.items() if field_name in values}


# This registry intentionally cannot be populated from ENV. No official-airline
# anonymous fare query currently has a safely replayable and approved schema.
OFFICIAL_AIRLINE_REQUEST_SCHEMAS: dict[str, OfficialAirlineRequestSchema] = {}
DEFAULT_AIRLINE_PUBLIC_USER_AGENT = "AITravelPlanner/0.1 public-airline-query"
DEFAULT_FLIGHT_CACHE_TTL_SECONDS = 60
DEFAULT_FLIGHT_SNAPSHOT_PATH = Path("logs/flight_harvest.sqlite3")
SPRING_AIRLINES_SOURCE_ID = "airline_9c_public_query"
SPRING_AIRLINES_SEARCH_PATH = "/Flights/SearchByTime"
HAINAN_AIRLINES_SOURCE_ID = "airline_hu_public_query"
HAINAN_AIRLINES_DEEP_LINK_PATH = "/hainanair/ibe/deeplink/ancillary.do"
HAINAN_AIRLINES_SEARCH_PATH = "/hainanair/ibe/common/processSearch.do"
QINGDAO_AIRLINES_SOURCE_ID = "airline_qw_public_query"
QINGDAO_AIRLINES_INIT_PATH = "/api/sale/v1/b2cTicket/get"
QINGDAO_AIRLINES_SEARCH_PATH = "/api/ewp/sales/v1/air/list"
SHANGHAI_TZ = timezone(timedelta(hours=8))
FLIGHT_CITY_QUERY_CODES: dict[str, str] = {
    "上海": "SHA",
    "北京": "BJS",
    "大连": "DLC",
    "广州": "CAN",
    "青岛": "TAO",
    "成都": "CTU",
    "深圳": "SZX",
    "杭州": "HGH",
    "西安": "XIY",
    "武汉": "WUH",
    "温州": "WNZ",
}

_RATE_LIMIT_LOCK = threading.Lock()
_LAST_PROVIDER_CALL_AT: dict[str, float] = {}
_SEARCH_CACHE: dict[str, tuple[float, list["FlightOffer"]]] = {}
_monotonic = time.monotonic
_sleep = time.sleep


@dataclass(frozen=True)
class FlightSearchRequest:
    origin_iata: str
    destination_iata: str
    departure_date: date
    origin_city_name: str | None = None
    destination_city_name: str | None = None
    adults: int = 1
    currency_code: str = "CNY"
    max_results: int = 5
    non_stop: bool | None = None
    query_scope: FlightQueryScope = "AIRPORT"
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    allowed_origin_airport_iatas: tuple[str, ...] = ()
    allowed_destination_airport_iatas: tuple[str, ...] = ()

    def for_query_scope(self, query_scope: FlightQueryScope) -> "FlightSearchRequest":
        return replace(self, query_scope=query_scope)


@dataclass
class FlightParseDiagnostics:
    raw_candidate_count: int = 0
    rejected_counts: dict[str, int] = field(default_factory=dict)

    def reject(self, reason_code: str) -> None:
        self.rejected_counts[reason_code] = self.rejected_counts.get(reason_code, 0) + 1


@dataclass(frozen=True)
class FlightOfferSegment:
    carrier_code: str
    flight_number: str
    origin_iata: str
    destination_iata: str
    departure_at: datetime | None
    arrival_at: datetime | None
    duration: str | None


@dataclass(frozen=True)
class FlightOfferCabinOption:
    option_id: str
    cabin_type: str
    price: Money
    availability: str
    source_option_version: str
    inventory_evidence: str
    remaining_count: int | None = None


@dataclass(frozen=True)
class FlightOffer:
    offer_id: str
    source: str
    total_price: Money
    currency: str
    segments: list[FlightOfferSegment]
    validating_airline_codes: list[str]
    raw_offer: dict[str, Any]
    data_source: DataSourceMetadata
    cabin_options: list[FlightOfferCabinOption]
    evidence_id: str


FlightProviderOutcomeStatus = Literal["VERIFIED", "EMPTY", "RATE_LIMITED", "TIMEOUT", "FAILED", "DISABLED"]


@dataclass(frozen=True)
class FlightProviderOutcome:
    source_id: str
    status: FlightProviderOutcomeStatus
    error_code: str | None
    retryable: bool
    offer_count: int
    message: str


@dataclass(frozen=True)
class FlightProviderSearchResult:
    offers: list[FlightOffer]
    attempted_source_ids: list[str]
    failure_message: str | None = None
    outcomes: list[FlightProviderOutcome] = field(default_factory=list)


@dataclass(frozen=True)
class FlightPriceResult:
    offer: FlightOffer | None
    attempted_source_ids: list[str]
    failure_message: str | None = None


@dataclass(frozen=True)
class FlightStateRequest:
    lamin: float
    lomin: float
    lamax: float
    lomax: float


@dataclass(frozen=True)
class FlightState:
    icao24: str
    callsign: str | None
    origin_country: str
    longitude: float | None
    latitude: float | None
    baro_altitude: float | None
    velocity: float | None
    true_track: float | None
    vertical_rate: float | None
    data_source: DataSourceMetadata


class FlightOfferProvider(Protocol):
    source_id: str
    query_scope: FlightQueryScope

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        ...


class FlightStateProvider(Protocol):
    source_id: str

    def get_states(self, request: FlightStateRequest) -> list[FlightState]:
        ...


def flight_data_source_metadata(
    source_id: str,
    source_name: str,
    *,
    cache_hit: bool = False,
    cache_ttl_seconds: int | None = None,
    evidence_id: str | None = None,
) -> DataSourceMetadata:
    is_official_airline = source_id.startswith("airline_") and source_id.endswith("_public_query")
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.FLIGHT,
        authority_level="A" if is_official_airline else "B",
        source_priority=10 if is_official_airline else None,
        source_region="CN" if is_official_airline else None,
        api_version=f"public_frontend_snapshot:{evidence_id}" if evidence_id else None,
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
        cache_ttl_seconds=cache_ttl_seconds,
        sla_level="PUBLIC_AIRLINE_FRONTEND_QUERY" if is_official_airline else "PUBLIC_READ_ONLY_RATE_LIMITED",
        cache_metadata=CacheMetadata(cacheable=True, cache_ttl_seconds=cache_ttl_seconds, cache_hit=cache_hit),
    )


class OfficialAirlinePublicQueryProvider:
    query_scope: FlightQueryScope = "AIRPORT"

    def __init__(
        self,
        *,
        source_id: str,
        source_name: str,
        allowed_carriers: tuple[str, ...],
        client: httpx.Client | None = None,
        base_url: str | None = None,
        search_path: str | None = None,
        user_agent: str | None = None,
        cache_ttl_seconds: int | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        request_schema: OfficialAirlineRequestSchema | None = None,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 1.0,
        snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
        snapshot_sqlite_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
    ) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.allowed_carriers = tuple(code.upper() for code in allowed_carriers)
        self.request_schema = request_schema or OFFICIAL_AIRLINE_REQUEST_SCHEMAS.get(source_id)
        self.allowed_hosts = tuple(host.lower().strip(".") for host in (allowed_hosts or ()))
        self.base_url = (base_url or "").rstrip("/")
        self.search_path = search_path or (self.request_schema.endpoint_path if self.request_schema else "")
        self.user_agent = user_agent or DEFAULT_AIRLINE_PUBLIC_USER_AGENT
        self.cache_ttl_seconds = cache_ttl_seconds if cache_ttl_seconds is not None else DEFAULT_FLIGHT_CACHE_TTL_SECONDS
        self.min_interval_seconds = min_interval_seconds
        self.snapshot_backend = snapshot_backend
        self.snapshot_sqlite_path = Path(snapshot_sqlite_path)
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False, headers=self._headers())

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        request = request.for_query_scope(self.query_scope)
        if self.request_schema is None:
            raise FlightProviderError(f"{self.source_id} has no verified request implementation")
        if not self.base_url:
            raise FlightProviderError(f"{self.source_id} base URL is not configured")
        if not self.search_path:
            raise FlightProviderError(f"{self.source_id} search path is not confirmed")
        if not _base_url_matches_allowed_hosts(self.base_url, self.allowed_hosts):
            raise FlightProviderError(f"{self.source_id} base URL is outside the source allowlist")

        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            logger.info("flight_public_cache_hit source_id=%s cache_key=%s offer_count=%s", self.source_id, cache_key, len(cached))
            return [_offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds) for offer in cached]

        _respect_provider_rate_limit(self.source_id, self.min_interval_seconds)
        endpoint = f"{self.base_url}{self.search_path if self.search_path.startswith('/') else '/' + self.search_path}"
        logger.info(
            "flight_public_search_start source_id=%s origin_iata=%s destination_iata=%s departure_date=%s",
            self.source_id,
            request.origin_iata,
            request.destination_iata,
            request.departure_date.isoformat(),
        )
        if self.request_schema.endpoint_method != "GET":
            raise FlightProviderError(f"{self.source_id} unsupported request method")
        request_values: dict[str, object] = {
            "origin_iata": request.origin_iata,
            "destination_iata": request.destination_iata,
            "departure_date": request.departure_date.isoformat(),
            "adults": request.adults,
            "currency_code": request.currency_code,
        }
        if request.non_stop is not None:
            request_values["non_stop"] = str(request.non_stop).lower()
        response = self.client.get(endpoint, params=self.request_schema.request_params(request_values), headers=self._headers())
        _raise_for_airline_risk_response(response, source_id=self.source_id)
        response.raise_for_status()
        payload = _response_payload(response)
        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=_response_text(response),
            content_type=str(response.headers.get("content-type", "")) if hasattr(response, "headers") else "",
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        offers = _parse_public_airline_payload(
            payload,
            request=request,
            source_id=self.source_id,
            source_name=self.source_name,
            allowed_carriers=self.allowed_carriers,
            evidence_id=snapshot_id,
            cache_ttl_seconds=self.cache_ttl_seconds,
        )
        raw_candidate_count = _public_airline_raw_candidate_count(payload)
        _log_flight_parse_diagnostics(
            source_id=self.source_id,
            evidence_id=snapshot_id,
            raw_candidate_count=raw_candidate_count,
            offers=offers,
            rejected_counts={"FLIGHT_PARSER_REJECTED_ALL": raw_candidate_count} if raw_candidate_count and not offers else {},
        )
        if raw_candidate_count > 0 and not offers:
            raise FlightParserRejectedAllError(
                f"FLIGHT_PARSER_REJECTED_ALL source_id={self.source_id} raw_candidate_count={raw_candidate_count}"
            )
        offers = sorted(offers, key=lambda offer: offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ))
        offers = offers[: max(1, request.max_results)]
        if offers:
            _cache_set(cache_key, offers, self.cache_ttl_seconds)
            save_flight_canonical_offers(
                source_id=self.source_id,
                request_key=cache_key,
                offers=offers,
                ttl_seconds=self.cache_ttl_seconds,
                snapshot_backend=self.snapshot_backend,
                snapshot_path=self.snapshot_sqlite_path,
            )
            logger.info("flight_public_search_success source_id=%s offer_count=%s", self.source_id, len(offers))
            return offers
        logger.info("flight_public_search_empty source_id=%s", self.source_id)
        return []

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }


class SpringAirlinesPublicQueryProvider:
    """Anonymous 9C fare search used by Spring Airlines' public booking page."""

    source_id = SPRING_AIRLINES_SOURCE_ID
    source_name = "Spring Airlines Official Public Flight Query"
    query_scope: FlightQueryScope = "CITY"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://flights.ch.com",
        user_agent: str = DEFAULT_AIRLINE_PUBLIC_USER_AGENT,
        cache_ttl_seconds: int = DEFAULT_FLIGHT_CACHE_TTL_SECONDS,
        allowed_hosts: tuple[str, ...] = ("flights.ch.com",),
        timeout_seconds: float = 60.0,
        snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
        snapshot_sqlite_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.cache_ttl_seconds = cache_ttl_seconds
        self.allowed_hosts = tuple(host.lower().strip(".") for host in allowed_hosts)
        self.snapshot_backend = snapshot_backend
        self.snapshot_sqlite_path = Path(snapshot_sqlite_path)
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers=self._headers(),
        )

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        request = request.for_query_scope(self.query_scope)
        if not _base_url_matches_allowed_hosts(self.base_url, self.allowed_hosts):
            raise FlightProviderError(f"{self.source_id} base URL is outside the source allowlist")
        if request.adults < 1:
            raise FlightProviderError(f"{self.source_id} adults must be positive")
        if request.currency_code.upper() != "CNY":
            raise FlightProviderError(f"{self.source_id} only supports CNY")
        if not request.origin_city_name or not request.destination_city_name:
            raise FlightProviderError(f"{self.source_id} requires origin and destination city names")

        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            logger.info(
                "flight_public_cache_hit source_id=%s cache_key=%s offer_count=%s",
                self.source_id,
                cache_key,
                len(cached),
            )
            return [
                _offer_with_cache_metadata(
                    offer,
                    cache_hit=True,
                    ttl_seconds=self.cache_ttl_seconds,
                )
                for offer in cached
            ]

        endpoint = f"{self.base_url}{SPRING_AIRLINES_SEARCH_PATH}"
        logger.info(
            "flight_public_search_start source_id=%s origin_iata=%s destination_iata=%s departure_date=%s",
            self.source_id,
            request.origin_iata,
            request.destination_iata,
            request.departure_date.isoformat(),
        )
        response = self.client.post(
            endpoint,
            data=_spring_airlines_form_data(request),
            headers=self._headers(request),
        )
        _raise_for_airline_risk_response(response, source_id=self.source_id)
        response.raise_for_status()
        payload = _response_payload(response)
        if str(payload.get("Code")) != "0":
            raise FlightProviderError(f"{self.source_id} returned business code {payload.get('Code')}")
        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=_response_text(response),
            content_type=str(response.headers.get("content-type", "")) if hasattr(response, "headers") else "",
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        diagnostics = FlightParseDiagnostics()
        offers = _parse_spring_airlines_payload(
            payload,
            request=request,
            evidence_id=snapshot_id,
            cache_ttl_seconds=self.cache_ttl_seconds,
            diagnostics=diagnostics,
        )
        _log_flight_parse_diagnostics(
            source_id=self.source_id,
            evidence_id=snapshot_id,
            raw_candidate_count=diagnostics.raw_candidate_count,
            offers=offers,
            rejected_counts=diagnostics.rejected_counts,
        )
        if diagnostics.raw_candidate_count > 0 and not offers:
            raise FlightParserRejectedAllError(
                f"FLIGHT_PARSER_REJECTED_ALL source_id={self.source_id} "
                f"raw_candidate_count={diagnostics.raw_candidate_count}"
            )
        offers.sort(
            key=lambda offer: (
                offer.total_price.amount_minor,
                offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ),
            )
        )
        offers = offers[: max(1, request.max_results)]
        if not offers:
            logger.info("flight_public_search_empty source_id=%s", self.source_id)
            return []

        _cache_set(cache_key, offers, self.cache_ttl_seconds)
        save_flight_canonical_offers(
            source_id=self.source_id,
            request_key=cache_key,
            offers=offers,
            ttl_seconds=self.cache_ttl_seconds,
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        logger.info("flight_public_search_success source_id=%s offer_count=%s", self.source_id, len(offers))
        return offers

    def _headers(self, request: FlightSearchRequest | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        if request is not None:
            headers["Referer"] = (
                f"{self.base_url}/{request.origin_iata.upper()}-{request.destination_iata.upper()}.html"
            )
        return headers


class HainanAirlinesPublicQueryProvider:
    """Anonymous fare search used by Hainan Airlines' public booking page."""

    source_id = HAINAN_AIRLINES_SOURCE_ID
    source_name = "Hainan Airlines Official Public Flight Query"
    query_scope: FlightQueryScope = "CITY"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://new.hnair.com",
        user_agent: str = DEFAULT_AIRLINE_PUBLIC_USER_AGENT,
        cache_ttl_seconds: int = DEFAULT_FLIGHT_CACHE_TTL_SECONDS,
        allowed_hosts: tuple[str, ...] = ("new.hnair.com",),
        timeout_seconds: float = 60.0,
        snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
        snapshot_sqlite_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.cache_ttl_seconds = cache_ttl_seconds
        self.allowed_hosts = tuple(host.lower().strip(".") for host in allowed_hosts)
        self.snapshot_backend = snapshot_backend
        self.snapshot_sqlite_path = Path(snapshot_sqlite_path)
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=self._headers(),
        )

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        request = request.for_query_scope(self.query_scope)
        self._validate_request(request)
        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            return [
                _offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds)
                for offer in cached
            ]

        params = _hainan_airlines_deep_link_params(request)
        deep_link_endpoint = f"{self.base_url}{HAINAN_AIRLINES_DEEP_LINK_PATH}"
        search_endpoint = f"{self.base_url}{HAINAN_AIRLINES_SEARCH_PATH}"
        logger.info(
            "flight_public_search_start source_id=%s origin_iata=%s destination_iata=%s departure_date=%s",
            self.source_id,
            request.origin_iata,
            request.destination_iata,
            request.departure_date.isoformat(),
        )
        first_response = self.client.get(deep_link_endpoint, params=params, headers=self._headers())
        _raise_for_airline_risk_response(first_response, source_id=self.source_id)
        first_response.raise_for_status()
        second_response = self.client.post(
            deep_link_endpoint,
            params={**params, "redirected": "true"},
            data={"ConversationID": "", "ENCRYPTED_QUERY": "", "QUERY": "", "redirected": "true"},
            headers=self._headers(),
        )
        _raise_for_airline_risk_response(second_response, source_id=self.source_id)
        second_response.raise_for_status()
        response = self.client.post(search_endpoint, data="", headers=self._headers())
        if getattr(response, "status_code", None) == 429:
            _raise_for_airline_risk_response(response, source_id=self.source_id)
        response.raise_for_status()
        response_text = _response_text(response)
        if "Flights[position] = Flight" not in response_text and _looks_like_airline_challenge(response_text):
            raise FlightProviderError(f"{self.source_id} anti-bot challenge detected; automated bypass is forbidden")

        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=_sanitize_hainan_snapshot(response_text),
            content_type=str(response.headers.get("content-type", "")) if hasattr(response, "headers") else "",
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        diagnostics = FlightParseDiagnostics()
        offers = _parse_hainan_airlines_response(
            response_text,
            request=request,
            evidence_id=snapshot_id,
            cache_ttl_seconds=self.cache_ttl_seconds,
            diagnostics=diagnostics,
        )
        _log_flight_parse_diagnostics(
            source_id=self.source_id,
            evidence_id=snapshot_id,
            raw_candidate_count=diagnostics.raw_candidate_count,
            offers=offers,
            rejected_counts=diagnostics.rejected_counts,
        )
        if diagnostics.raw_candidate_count > 0 and not offers:
            raise FlightParserRejectedAllError(
                f"FLIGHT_PARSER_REJECTED_ALL source_id={self.source_id} "
                f"raw_candidate_count={diagnostics.raw_candidate_count}"
            )
        offers.sort(
            key=lambda offer: (
                offer.total_price.amount_minor,
                offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ),
            )
        )
        offers = offers[: max(1, request.max_results)]
        if not offers:
            logger.info("flight_public_search_empty source_id=%s", self.source_id)
            return []
        _cache_set(cache_key, offers, self.cache_ttl_seconds)
        save_flight_canonical_offers(
            source_id=self.source_id,
            request_key=cache_key,
            offers=offers,
            ttl_seconds=self.cache_ttl_seconds,
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        logger.info("flight_public_search_success source_id=%s offer_count=%s", self.source_id, len(offers))
        return offers

    def _validate_request(self, request: FlightSearchRequest) -> None:
        if not _base_url_matches_allowed_hosts(self.base_url, self.allowed_hosts):
            raise FlightProviderError(f"{self.source_id} base URL is outside the source allowlist")
        if request.adults < 1:
            raise FlightProviderError(f"{self.source_id} adults must be positive")
        if request.currency_code.upper() != "CNY":
            raise FlightProviderError(f"{self.source_id} only supports CNY")

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.base_url}/",
        }


class QingdaoAirlinesPublicQueryProvider:
    """Anonymous QW fare search used by Qingdao Airlines' public booking page."""

    source_id = QINGDAO_AIRLINES_SOURCE_ID
    source_name = "Qingdao Airlines Official Public Flight Query"
    query_scope: FlightQueryScope = "AIRPORT"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://www.qdairlines.com",
        user_agent: str = DEFAULT_AIRLINE_PUBLIC_USER_AGENT,
        cache_ttl_seconds: int = DEFAULT_FLIGHT_CACHE_TTL_SECONDS,
        allowed_hosts: tuple[str, ...] = ("www.qdairlines.com",),
        timeout_seconds: float = 60.0,
        snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
        snapshot_sqlite_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.cache_ttl_seconds = cache_ttl_seconds
        self.allowed_hosts = tuple(host.lower().strip(".") for host in allowed_hosts)
        self.snapshot_backend = snapshot_backend
        self.snapshot_sqlite_path = Path(snapshot_sqlite_path)
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        request = request.for_query_scope(self.query_scope)
        self._validate_request(request)
        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            return [
                _offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds)
                for offer in cached
            ]

        cookie_id = uuid4().hex
        init_endpoint = f"{self.base_url}{QINGDAO_AIRLINES_INIT_PATH}"
        search_endpoint = f"{self.base_url}{QINGDAO_AIRLINES_SEARCH_PATH}"
        init_response = self.client.get(
            init_endpoint,
            params={"cookieId": cookie_id},
            headers=self._headers(),
        )
        _raise_for_airline_risk_response(init_response, source_id=self.source_id)
        init_response.raise_for_status()
        init_payload = init_response.json()
        if not isinstance(init_payload, dict):
            raise FlightProviderError(f"{self.source_id} returned an invalid anonymous initialization payload")
        now = datetime.now(SHANGHAI_TZ)
        request_body = _qingdao_airlines_request_body(
            request,
            cookie_id=cookie_id,
            trick_token=_qingdao_airlines_trick_token(init_payload, now),
        )
        response = self.client.post(
            search_endpoint,
            json=request_body,
            headers=self._headers(now),
        )
        _raise_for_airline_risk_response(response, source_id=self.source_id)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise FlightProviderError(f"{self.source_id} returned an invalid response payload")
        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=_response_text(response),
            content_type=str(response.headers.get("content-type", "")) if hasattr(response, "headers") else "",
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        if str(payload.get("code")) != "1":
            code = str(payload.get("code"))
            business_message = str(payload.get("message") or payload.get("msg") or "").strip()
            if code == "0" and re.search(r"未查询到航班|没有航班|无航班|no flights?", business_message, flags=re.IGNORECASE):
                logger.info("flight_public_search_empty source_id=%s business_code=%s", self.source_id, code)
                return []
            raise FlightProviderError(
                f"{self.source_id} returned business code {code}"
                + (f" ({business_message})" if business_message else "")
            )
        diagnostics = FlightParseDiagnostics()
        offers = _parse_qingdao_airlines_payload(
            payload,
            request=request,
            evidence_id=snapshot_id,
            cache_ttl_seconds=self.cache_ttl_seconds,
            diagnostics=diagnostics,
        )
        _log_flight_parse_diagnostics(
            source_id=self.source_id,
            evidence_id=snapshot_id,
            raw_candidate_count=diagnostics.raw_candidate_count,
            offers=offers,
            rejected_counts=diagnostics.rejected_counts,
        )
        if diagnostics.raw_candidate_count > 0 and not offers:
            raise FlightParserRejectedAllError(
                f"FLIGHT_PARSER_REJECTED_ALL source_id={self.source_id} "
                f"raw_candidate_count={diagnostics.raw_candidate_count}"
            )
        offers.sort(
            key=lambda offer: (
                offer.total_price.amount_minor,
                offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ),
            )
        )
        offers = offers[: max(1, request.max_results)]
        if not offers:
            logger.info("flight_public_search_empty source_id=%s", self.source_id)
            return []
        _cache_set(cache_key, offers, self.cache_ttl_seconds)
        save_flight_canonical_offers(
            source_id=self.source_id,
            request_key=cache_key,
            offers=offers,
            ttl_seconds=self.cache_ttl_seconds,
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        logger.info("flight_public_search_success source_id=%s offer_count=%s", self.source_id, len(offers))
        return offers

    def _validate_request(self, request: FlightSearchRequest) -> None:
        if not _base_url_matches_allowed_hosts(self.base_url, self.allowed_hosts):
            raise FlightProviderError(f"{self.source_id} base URL is outside the source allowlist")
        if request.adults < 1:
            raise FlightProviderError(f"{self.source_id} adults must be positive")
        if request.currency_code.upper() != "CNY":
            raise FlightProviderError(f"{self.source_id} only supports CNY")
        if not request.origin_city_name or not request.destination_city_name:
            raise FlightProviderError(f"{self.source_id} requires origin and destination city names")

    def _headers(self, now: datetime | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }
        if now is not None:
            timestamp = str(int(now.timestamp() * 1000))
            token_input = f"b2cjhfkjashdfli654654{timestamp}".encode("utf-8")
            headers.update(
                {
                    "Content-Type": "application/json;charset=UTF-8",
                    "sellerId": "B2C",
                    "timestamp": timestamp,
                    "token": hashlib.md5(token_input, usedforsecurity=False).hexdigest().upper(),
                }
            )
        return headers


class OpenSkyStatesProvider:
    source_id = "opensky_states"

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://opensky-network.org",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.base_url = base_url.rstrip("/")

    def get_states(self, request: FlightStateRequest) -> list[FlightState]:
        response = self.client.get(
            f"{self.base_url}/api/states/all",
            params={
                "lamin": request.lamin,
                "lomin": request.lomin,
                "lamax": request.lamax,
                "lomax": request.lomax,
            },
        )
        response.raise_for_status()
        payload = response.json()
        states = payload.get("states")
        if states is None:
            return []
        return [self._parse_state(item) for item in states]

    def _parse_state(self, item: list[Any]) -> FlightState:
        return FlightState(
            icao24=str(item[0] or ""),
            callsign=str(item[1]).strip() if len(item) > 1 and item[1] else None,
            origin_country=str(item[2] or ""),
            longitude=_optional_float(item[5] if len(item) > 5 else None),
            latitude=_optional_float(item[6] if len(item) > 6 else None),
            baro_altitude=_optional_float(item[7] if len(item) > 7 else None),
            velocity=_optional_float(item[9] if len(item) > 9 else None),
            true_track=_optional_float(item[10] if len(item) > 10 else None),
            vertical_rate=_optional_float(item[11] if len(item) > 11 else None),
            data_source=flight_data_source_metadata(self.source_id, "OpenSky Network States API"),
        )


def build_enabled_flight_providers(environment: str | None = None) -> list[FlightOfferProvider]:
    from app.data_sources.provider_registry import build_enabled_providers

    providers: list[FlightOfferProvider] = []
    for provider in build_enabled_providers(
        {
            "spring_airlines_public_query",
            "hainan_airlines_public_query",
            "qingdao_airlines_public_query",
            "browser_airline_flight",
        },
        environment,
    ):
        query_scope = getattr(provider, "query_scope", None)
        if query_scope not in {"CITY", "AIRPORT"}:
            logger.error(
                "flight_provider_missing_query_scope source_id=%s",
                getattr(provider, "source_id", "unknown"),
            )
            continue
        providers.append(cast(FlightOfferProvider, provider))
    return providers


def build_enabled_flight_state_providers(environment: str | None = None) -> list[FlightStateProvider]:
    from app.data_sources.provider_registry import build_enabled_providers

    return [
        cast(FlightStateProvider, provider)
        for provider in build_enabled_providers({"opensky_states"}, environment)
    ]


def flight_city_query_code(city_name: str, fallback_airport_iata: str | None = None) -> str | None:
    explicit = FLIGHT_CITY_QUERY_CODES.get(city_name.strip())
    if explicit:
        return explicit
    fallback = (fallback_airport_iata or "").strip().upper()
    return fallback if re.fullmatch(r"[A-Z]{3}", fallback) else None


def _provider_search_requests(
    provider: FlightOfferProvider,
    request: FlightSearchRequest | FlightSearchScope,
) -> list[FlightSearchRequest]:
    query_scope = getattr(provider, "query_scope", None)
    if isinstance(request, FlightSearchRequest):
        if query_scope not in {"CITY", "AIRPORT"}:
            query_scope = request.query_scope
        return [request.for_query_scope(cast(FlightQueryScope, query_scope))]
    if query_scope == "CITY":
        origin_city_code = flight_city_query_code(
            request.origin_city_name,
            request.origin_city_code,
        )
        destination_city_code = flight_city_query_code(
            request.destination_city_name,
            request.destination_city_code,
        )
        if not origin_city_code or not destination_city_code:
            return []
        return [
            FlightSearchRequest(
                origin_iata=origin_city_code,
                destination_iata=destination_city_code,
                departure_date=request.departure_date,
                origin_city_name=request.origin_city_name,
                destination_city_name=request.destination_city_name,
                adults=request.adults,
                currency_code=request.currency_code,
                max_results=request.max_results,
                non_stop=request.non_stop,
                query_scope="CITY",
                origin_city_code=origin_city_code,
                destination_city_code=destination_city_code,
                allowed_origin_airport_iatas=_normalized_iata_tuple(
                    request.allowed_origin_airport_iatas
                ),
                allowed_destination_airport_iatas=_normalized_iata_tuple(
                    request.allowed_destination_airport_iatas
                ),
            )
        ]
    if query_scope == "AIRPORT":
        return [
            FlightSearchRequest(
                origin_iata=origin_iata,
                destination_iata=destination_iata,
                departure_date=request.departure_date,
                origin_city_name=request.origin_city_name,
                destination_city_name=request.destination_city_name,
                adults=request.adults,
                currency_code=request.currency_code,
                max_results=request.max_results,
                non_stop=request.non_stop,
                query_scope="AIRPORT",
                origin_city_code=request.origin_city_code,
                destination_city_code=request.destination_city_code,
                allowed_origin_airport_iatas=(origin_iata,),
                allowed_destination_airport_iatas=(destination_iata,),
            )
            for origin_iata in _normalized_iata_tuple(
                request.allowed_origin_airport_iatas
            )
            for destination_iata in _normalized_iata_tuple(
                request.allowed_destination_airport_iatas
            )
        ]
    return []


def _normalized_iata_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            code.strip().upper()
            for code in values
            if re.fullmatch(r"[A-Za-z]{3}", code.strip())
        )
    )


def _deduplicate_flight_offers(offers: list[FlightOffer]) -> list[FlightOffer]:
    deduplicated: list[FlightOffer] = []
    seen: set[tuple[tuple[str, str, str, str, str, str], ...]] = set()
    for offer in offers:
        identity = tuple(
            (
                segment.carrier_code.upper(),
                segment.flight_number.upper(),
                segment.origin_iata.upper(),
                segment.destination_iata.upper(),
                segment.departure_at.isoformat() if segment.departure_at else "",
                segment.arrival_at.isoformat() if segment.arrival_at else "",
            )
            for segment in offer.segments
        )
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(offer)
    return deduplicated


def search_flight_offers_with_enabled_provider(
    request: FlightSearchRequest | FlightSearchScope,
    environment: str | None = None,
) -> list[FlightOffer]:
    return search_flight_offers_with_enabled_provider_result(request, environment).offers


def search_flight_offers_with_enabled_provider_result(
    request: FlightSearchRequest | FlightSearchScope,
    environment: str | None = None,
) -> FlightProviderSearchResult:
    attempted_source_ids: list[str] = []
    offers: list[FlightOffer] = []
    outcomes: list[FlightProviderOutcome] = []
    providers = build_enabled_flight_providers(environment)
    if not providers:
        return FlightProviderSearchResult(
            offers=[],
            attempted_source_ids=[],
            failure_message="no enabled approved official-airline flight provider",
            outcomes=[
                FlightProviderOutcome(
                    source_id="airline_public_query",
                    status="DISABLED",
                    error_code="FLIGHT_PROVIDER_DISABLED",
                    retryable=False,
                    offer_count=0,
                    message="no enabled approved official-airline flight provider",
                )
            ],
        )
    for provider in providers:
        attempted_source_ids.append(provider.source_id)
        provider_offers: list[FlightOffer] = []
        provider_failures: list[FlightProviderOutcome] = []
        provider_requests = _provider_search_requests(provider, request)
        if not provider_requests:
            provider_failures.append(
                FlightProviderOutcome(
                    source_id=provider.source_id,
                    status="FAILED",
                    error_code="FLIGHT_CITY_CODE_UNAVAILABLE",
                    retryable=False,
                    offer_count=0,
                    message="provider city query code is unavailable",
                )
            )
        for provider_request in provider_requests:
            try:
                provider_offers.extend(provider.search_offers(provider_request))
            except (httpx.HTTPError, FlightProviderError, ValueError, KeyError) as exc:
                provider_failures.append(_flight_provider_failure_outcome(provider.source_id, exc))
                logger.warning(
                    "flight_provider_search_failure source_id=%s query_scope=%s route=%s->%s error=%s",
                    provider.source_id,
                    getattr(provider, "query_scope", provider_request.query_scope),
                    provider_request.origin_iata,
                    provider_request.destination_iata,
                    exc,
                )
        provider_offers = _deduplicate_flight_offers(provider_offers)
        offers.extend(provider_offers)
        if provider_offers:
            outcomes.append(
                FlightProviderOutcome(
                    source_id=provider.source_id,
                    status="VERIFIED",
                    error_code=None,
                    retryable=False,
                    offer_count=len(provider_offers),
                    message=f"verified {len(provider_offers)} flight offers",
                )
            )
        elif provider_failures:
            outcomes.append(provider_failures[0])
        else:
            outcomes.append(
                FlightProviderOutcome(
                    source_id=provider.source_id,
                    status="EMPTY",
                    error_code="FLIGHT_PROVIDER_EMPTY",
                    retryable=False,
                    offer_count=0,
                    message="provider query completed with no verifiable flight offers",
                )
            )
    offers.sort(
        key=lambda offer: (
            offer.total_price.amount_minor,
            offer.segments[0].departure_at if offer.segments and offer.segments[0].departure_at else datetime.max.replace(tzinfo=SHANGHAI_TZ),
            offer.offer_id,
        )
    )
    failure_messages = [f"{outcome.source_id}: {outcome.message}" for outcome in outcomes if outcome.status != "VERIFIED"]
    return FlightProviderSearchResult(
        offers=_deduplicate_flight_offers(offers)[: max(1, request.max_results)],
        attempted_source_ids=attempted_source_ids,
        failure_message="; ".join(failure_messages) or None,
        outcomes=outcomes,
    )


def _flight_provider_failure_outcome(source_id: str, exc: Exception) -> FlightProviderOutcome:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if isinstance(exc, httpx.TimeoutException) or any(marker in lowered for marker in ("timeout", "timed out")):
        status: FlightProviderOutcomeStatus = "TIMEOUT"
        error_code = "FLIGHT_PROVIDER_TIMEOUT"
        retryable = True
    elif "rate limit" in lowered or "http 429" in lowered:
        status = "RATE_LIMITED"
        error_code = "FLIGHT_PROVIDER_RATE_LIMITED"
        retryable = True
    elif any(marker in lowered for marker in ("challenge", "captcha", "anti-bot", "waf")):
        status = "FAILED"
        error_code = "FLIGHT_PROVIDER_CHALLENGE"
        retryable = True
    elif any(marker in lowered for marker in ("not enabled", "not configured", "not implemented", "disabled")):
        status = "DISABLED"
        error_code = "FLIGHT_PROVIDER_DISABLED"
        retryable = False
    elif isinstance(exc, FlightParserRejectedAllError) or "flight_parser_rejected_all" in lowered:
        status = "FAILED"
        error_code = "FLIGHT_PARSER_REJECTED_ALL"
        retryable = False
    elif isinstance(exc, httpx.TransportError):
        status = "FAILED"
        error_code = "FLIGHT_PROVIDER_FAILED"
        retryable = True
    else:
        status = "FAILED"
        error_code = "FLIGHT_PROVIDER_INVALID_RESPONSE"
        retryable = False
    return FlightProviderOutcome(
        source_id=source_id,
        status=status,
        error_code=error_code,
        retryable=retryable,
        offer_count=0,
        message=message,
    )


def price_flight_offer_with_enabled_provider_result(offer: FlightOffer, environment: str | None = None) -> FlightPriceResult:
    return FlightPriceResult(offer=offer, attempted_source_ids=[offer.data_source.source_id], failure_message=None)


def get_flight_states_with_enabled_provider(request: FlightStateRequest, environment: str | None = None) -> list[FlightState]:
    for provider in build_enabled_flight_state_providers(environment):
        try:
            states = provider.get_states(request)
            if states:
                return states
        except (httpx.HTTPError, FlightProviderError, ValueError):
            continue
    return []


def save_flight_raw_snapshot(
    *,
    source_id: str,
    request_key: str,
    payload_text: str,
    content_type: str,
    snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
    snapshot_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
) -> str:
    snapshot_id = f"fltraw_{uuid4().hex[:12]}"
    if snapshot_backend == "disabled":
        return snapshot_id
    path = Path(snapshot_path)
    _init_flight_snapshot_store(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO flight_raw_snapshots(snapshot_id, source_id, request_key, payload_text, content_type, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                source_id,
                _request_key_fingerprint(request_key),
                redact_flight_snapshot(payload_text),
                content_type,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return snapshot_id


def save_flight_canonical_offers(
    *,
    source_id: str,
    request_key: str,
    offers: list[FlightOffer],
    ttl_seconds: int,
    snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
    snapshot_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
) -> None:
    if snapshot_backend == "disabled":
        return
    path = Path(snapshot_path)
    _init_flight_snapshot_store(path)
    indexed_at = datetime.now(timezone.utc)
    expires_at = indexed_at + timedelta(seconds=max(0, ttl_seconds))
    with sqlite3.connect(path) as conn:
        for offer in offers:
            conn.execute(
                """
                INSERT OR REPLACE INTO flight_canonical_offers(offer_id, source_id, request_key, offer_json, indexed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    offer.offer_id,
                    source_id,
                    _request_key_fingerprint(request_key),
                    _offer_to_json(offer),
                    indexed_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )


def _spring_airlines_form_data(request: FlightSearchRequest) -> dict[str, str]:
    return {
        "Active9s": "",
        "IsJC": "false",
        "IsShowTaxprice": "false",
        "Currency": "0",
        "SType": "0",
        "Departure": request.origin_city_name or "",
        "Arrival": request.destination_city_name or "",
        "DepartureDate": request.departure_date.isoformat(),
        "ReturnDate": "",
        "IsIJFlight": "false",
        "IsBg": "false",
        "IsEmployee": "false",
        "IsLittleGroupFlight": "false",
        "SeatsNum": str(request.adults),
        "ActId": "0",
        "IfRet": "false",
        "IsUM": "false",
        "SpecTravTypeId": "0",
        "IsContains9CAndIJ": "false",
        "DepCityCode": request.origin_iata.upper(),
        "ArrCityCode": request.destination_iata.upper(),
        "DepAirportCode": "",
        "ArrAirportCode": "",
        "IsSearchDepAirport": "false",
        "IsSearchArrAirport": "false",
    }


def _parse_spring_airlines_payload(
    payload: dict[str, Any],
    *,
    request: FlightSearchRequest,
    evidence_id: str,
    cache_ttl_seconds: int,
    diagnostics: FlightParseDiagnostics | None = None,
) -> list[FlightOffer]:
    diagnostics = diagnostics or FlightParseDiagnostics()
    raw_routes = payload.get("Route")
    if not isinstance(raw_routes, list):
        return []

    offers: list[FlightOffer] = []
    for route_group in raw_routes:
        raw_flights = route_group if isinstance(route_group, list) else [route_group]
        for raw_flight in raw_flights:
            if not isinstance(raw_flight, dict):
                continue
            diagnostics.raw_candidate_count += 1
            flight_no = str(raw_flight.get("No") or "").strip().upper()
            if not re.fullmatch(r"9C\d+[A-Z]?", flight_no):
                diagnostics.reject("FLIGHT_NUMBER_INVALID")
                continue
            departure_city_code = str(raw_flight.get("DepartureCode") or "").strip().upper()
            arrival_city_code = str(raw_flight.get("ArrivalCode") or "").strip().upper()
            expected_origin_city_code = (request.origin_city_code or request.origin_iata).upper()
            expected_destination_city_code = (request.destination_city_code or request.destination_iata).upper()
            if (
                departure_city_code != expected_origin_city_code
                or arrival_city_code != expected_destination_city_code
            ):
                diagnostics.reject("FLIGHT_CITY_CODE_MISMATCH")
                continue
            origin_iata = str(raw_flight.get("DepartureAirportCode") or "").strip().upper()
            destination_iata = str(raw_flight.get("ArrivalAirportCode") or "").strip().upper()
            if not _actual_airport_is_allowed(origin_iata, request, origin=True) or not _actual_airport_is_allowed(
                destination_iata, request, origin=False
            ):
                diagnostics.reject(
                    "FLIGHT_AIRPORT_UNRESOLVED"
                    if not re.fullmatch(r"[A-Z]{3}", origin_iata)
                    or not re.fullmatch(r"[A-Z]{3}", destination_iata)
                    else "FLIGHT_AIRPORT_OUT_OF_SCOPE"
                )
                continue
            stopovers = raw_flight.get("Stopovers")
            if request.non_stop is True and isinstance(stopovers, list) and stopovers:
                diagnostics.reject("FLIGHT_NON_STOP_REQUIRED")
                continue
            departure_at = _parse_datetime(raw_flight.get("DepartureTime"), request.departure_date)
            arrival_at = _parse_datetime(raw_flight.get("ArrivalTime"), request.departure_date)
            if departure_at is None or arrival_at is None or arrival_at <= departure_at:
                diagnostics.reject("FLIGHT_TIME_INVALID")
                continue
            cabins = _spring_airlines_cabin_options(
                raw_flight,
                flight_no=flight_no,
                evidence_id=evidence_id,
            )
            if not cabins:
                diagnostics.reject("FLIGHT_CABIN_UNAVAILABLE")
                continue
            selected = min(cabins, key=lambda cabin: cabin.price.amount_minor)
            segment_id = str(raw_flight.get("SegmentId") or raw_flight.get("RouteId") or "").strip()
            offer_id = segment_id or f"spring_{flight_no}_{request.departure_date.isoformat()}"
            data_source = flight_data_source_metadata(
                SPRING_AIRLINES_SOURCE_ID,
                SpringAirlinesPublicQueryProvider.source_name,
                cache_hit=False,
                cache_ttl_seconds=cache_ttl_seconds,
                evidence_id=evidence_id,
            )
            offers.append(
                FlightOffer(
                    offer_id=offer_id,
                    source="SPRING_AIRLINES_PUBLIC_FRONTEND",
                    total_price=selected.price,
                    currency=selected.price.currency,
                    segments=[
                        FlightOfferSegment(
                            carrier_code="9C",
                            flight_number=flight_no[2:],
                            origin_iata=origin_iata,
                            destination_iata=destination_iata,
                            departure_at=departure_at,
                            arrival_at=arrival_at,
                            duration=str(raw_flight.get("FlightTimeM") or raw_flight.get("FlightTime") or "") or None,
                        )
                    ],
                    validating_airline_codes=["9C"],
                    raw_offer={
                        "flight_number": flight_no,
                        "segment_id": segment_id or None,
                        "departure_airport": raw_flight.get("DepartureStation"),
                        "arrival_airport": raw_flight.get("ArrivalStation"),
                        "evidence_id": evidence_id,
                    },
                    data_source=data_source,
                    cabin_options=cabins,
                    evidence_id=evidence_id,
                )
            )
    return offers


def _spring_airlines_cabin_options(
    raw_flight: dict[str, Any],
    *,
    flight_no: str,
    evidence_id: str,
) -> list[FlightOfferCabinOption]:
    groups = raw_flight.get("AircraftCabins")
    if not isinstance(groups, list):
        return []
    cabins: list[FlightOfferCabinOption] = []
    for group_index, group in enumerate(groups, start=1):
        if not isinstance(group, dict) or group.get("IsHide") is True:
            continue
        raw_infos = group.get("AircraftCabinInfos")
        if not isinstance(raw_infos, list):
            continue
        cabin_type = _spring_airlines_cabin_type(group)
        for info_index, info in enumerate(raw_infos, start=1):
            if not isinstance(info, dict):
                continue
            price = _money_from_value(info.get("Price"))
            if price is None or price.amount_minor <= 0:
                continue
            fare_code = str(info.get("Name") or f"fare_{group_index}_{info_index}").strip()
            remaining = _optional_int(info.get("Remain"))
            availability = "LIMITED" if remaining is not None and remaining > 0 else "AVAILABLE"
            remaining_count = remaining if remaining is not None and remaining > 0 else None
            option_token = _normalize_option_token(f"{fare_code}_{group_index}_{info_index}_{price.amount_minor}")
            cabins.append(
                FlightOfferCabinOption(
                    option_id=f"spring_{flight_no.lower()}_{option_token}",
                    cabin_type=cabin_type,
                    price=price,
                    availability=availability,
                    source_option_version=f"spring_{flight_no}_{evidence_id}_{option_token}",
                    inventory_evidence=f"public_response_price_with_remain={remaining if remaining is not None else 'unknown'}",
                    remaining_count=remaining_count,
                )
            )
    return cabins


def _spring_airlines_cabin_type(group: dict[str, Any]) -> str:
    label = str(group.get("CabinLevelName") or "").strip()
    for expected in ("头等舱", "商务舱", "经济舱"):
        if expected in label:
            return expected
    return "经济舱"


def _hainan_airlines_deep_link_params(request: FlightSearchRequest) -> dict[str, str]:
    return {
        "PRE": "F",
        "PT": "F",
        "MO": "T",
        "SC": "A",
        "TA": str(request.adults),
        "TG": "0",
        "TC": "0",
        "TI": "0",
        "ICS": "F",
        "ORI": request.origin_iata.upper(),
        "DES": request.destination_iata.upper(),
        "FLC": "1",
        "DD1": request.departure_date.isoformat(),
        "CTRY": "CN",
        "LAN": "zh",
        "SRC": "hn",
    }


def _parse_hainan_airlines_response(
    response_text: str,
    *,
    request: FlightSearchRequest,
    evidence_id: str,
    cache_ttl_seconds: int,
    diagnostics: FlightParseDiagnostics | None = None,
) -> list[FlightOffer]:
    diagnostics = diagnostics or FlightParseDiagnostics()
    flight_blocks = re.findall(
        r"var\s+Flight\s*=\s*\{\};(?P<body>.*?)Flights\[position\]\s*=\s*Flight;",
        response_text,
        flags=re.DOTALL,
    )
    offers: list[FlightOffer] = []
    allowed_carriers = {"HU", "Y8", "JD", "8L", "UQ", "FU", "GX", "CN"}
    for block in flight_blocks:
        diagnostics.raw_candidate_count += 1
        if len(re.findall(r"var\s+Segment\s*=\s*\{\};", block)) != 1:
            diagnostics.reject("FLIGHT_SEGMENT_STRUCTURE_INVALID")
            continue
        carrier = _js_assignment(block, "Segment.marketingAirlineEN").upper()
        flight_number = _js_assignment(block, "Segment.marketingFlightNum").upper()
        if carrier not in allowed_carriers or not re.fullmatch(r"\d{3,4}[A-Z]?", flight_number):
            diagnostics.reject("FLIGHT_NUMBER_INVALID")
            continue
        origin_iata = _js_assignment(block, "Segment.departureIATA").upper()
        destination_iata = _js_assignment(block, "Segment.arrivalIATA").upper()
        if not re.fullmatch(r"[A-Z]{3}", origin_iata) or not re.fullmatch(r"[A-Z]{3}", destination_iata):
            diagnostics.reject("FLIGHT_AIRPORT_UNRESOLVED")
            continue
        if not _actual_airport_is_allowed(origin_iata, request, origin=True) or not _actual_airport_is_allowed(
            destination_iata, request, origin=False
        ):
            diagnostics.reject("FLIGHT_AIRPORT_OUT_OF_SCOPE")
            continue
        departure_date_text = _js_assignment(block, "Segment.departureDate")
        departure_time_text = _js_assignment(block, "Segment.departureTime")
        arrival_date_text = _js_assignment(block, "Segment.arrivalDate")
        arrival_time_text = _js_assignment(block, "Segment.arrivalTime")
        if not all((departure_date_text, departure_time_text, arrival_date_text, arrival_time_text)):
            diagnostics.reject("FLIGHT_TIME_INVALID")
            continue
        departure_at = _parse_datetime(
            f"{departure_date_text}T{departure_time_text}",
            request.departure_date,
        )
        arrival_at = _parse_datetime(
            f"{arrival_date_text}T{arrival_time_text}",
            request.departure_date,
        )
        if (
            departure_at is None
            or arrival_at is None
            or departure_at.date() != request.departure_date
            or arrival_at <= departure_at
        ):
            diagnostics.reject("FLIGHT_TIME_INVALID")
            continue
        cabins = _hainan_airlines_cabin_options(
            block,
            flight_no=f"{carrier}{flight_number}",
            evidence_id=evidence_id,
        )
        if not cabins:
            diagnostics.reject("FLIGHT_CABIN_UNAVAILABLE")
            continue
        selected = min(cabins, key=lambda cabin: cabin.price.amount_minor)
        duration_hour = _js_assignment(block, "Segment.durationHour")
        duration_minute = _js_assignment(block, "Segment.durationMin")
        duration = f"PT{duration_hour or '0'}H{duration_minute or '0'}M"
        offer_id = (
            f"hainan_{carrier.lower()}{flight_number.lower()}_"
            f"{departure_at.date().isoformat()}_{origin_iata.lower()}_{destination_iata.lower()}"
        )
        offers.append(
            FlightOffer(
                offer_id=offer_id,
                source="HAINAN_AIRLINES_PUBLIC_FRONTEND",
                total_price=selected.price,
                currency=selected.price.currency,
                segments=[
                    FlightOfferSegment(
                        carrier_code=carrier,
                        flight_number=flight_number,
                        origin_iata=origin_iata,
                        destination_iata=destination_iata,
                        departure_at=departure_at,
                        arrival_at=arrival_at,
                        duration=duration,
                    )
                ],
                validating_airline_codes=[carrier],
                raw_offer={
                    "flight_number": f"{carrier}{flight_number}",
                    "departure_airport": _js_assignment(block, "Segment.departureAirportName"),
                    "arrival_airport": _js_assignment(block, "Segment.arrivalAirportName"),
                    "equipment": _js_assignment(block, "Segment.EquipType"),
                    "evidence_id": evidence_id,
                },
                data_source=flight_data_source_metadata(
                    HAINAN_AIRLINES_SOURCE_ID,
                    HainanAirlinesPublicQueryProvider.source_name,
                    cache_hit=False,
                    cache_ttl_seconds=cache_ttl_seconds,
                    evidence_id=evidence_id,
                ),
                cabin_options=cabins,
                evidence_id=evidence_id,
            )
        )
    return offers


def _hainan_airlines_cabin_options(
    flight_block: str,
    *,
    flight_no: str,
    evidence_id: str,
) -> list[FlightOfferCabinOption]:
    fare_blocks = re.findall(
        r"var\s+FareInfo\s*=\s*\{\};(?P<body>.*?)FareInfos\[FareInfosCode\]\s*=\s*FareInfo;",
        flight_block,
        flags=re.DOTALL,
    )
    cabins: list[FlightOfferCabinOption] = []
    seen: set[tuple[str, str, int]] = set()
    for index, fare_block in enumerate(fare_blocks, start=1):
        fare_code = _js_assignment(fare_block, "FareInfo.resBookDesigCode").upper()
        cabin_code = _js_assignment(fare_block, "FareInfo.cabinCode").upper()
        fare_family = _js_assignment(fare_block, "FareInfo.fareFamilyName")
        price = _money_from_value(
            _js_assignment(fare_block, "priceDetails.totalAmount")
            or _js_assignment(fare_block, "priceDetails.baseAmount")
        )
        if price is None or price.amount_minor <= 0:
            continue
        identity = (fare_code, fare_family, price.amount_minor)
        if identity in seen:
            continue
        seen.add(identity)
        seat_value = _js_assignment(fare_block, "seatDetails.seatNum").upper()
        remaining = _optional_int(seat_value) if seat_value != "A" else None
        if remaining == 0:
            continue
        availability = "LIMITED" if remaining is not None and remaining > 0 else "AVAILABLE"
        cabin_type = _hainan_airlines_cabin_type(cabin_code, fare_family)
        option_token = _normalize_option_token(
            f"{fare_code or cabin_code}_{fare_family}_{index}_{price.amount_minor}"
        )
        cabins.append(
            FlightOfferCabinOption(
                option_id=f"hainan_{flight_no.lower()}_{option_token}",
                cabin_type=cabin_type,
                price=price,
                availability=availability,
                source_option_version=f"hainan_{flight_no}_{evidence_id}_{option_token}",
                inventory_evidence=f"public_response_seatNum={seat_value or 'unknown'}",
                remaining_count=remaining if remaining is not None and remaining > 0 else None,
            )
        )
    return cabins


def _hainan_airlines_cabin_type(cabin_code: str, fare_family: str) -> str:
    if cabin_code == "F" or "头等" in fare_family:
        return "FIRST"
    if cabin_code == "C" or "公务" in fare_family or "商务" in fare_family:
        return "BUSINESS"
    if cabin_code == "W" or "超级经济" in fare_family:
        return "PREMIUM_ECONOMY"
    return "ECONOMY"


def _js_assignment(block: str, property_name: str) -> str:
    match = re.search(rf"{re.escape(property_name)}\s*=\s*'([^']*)'", block)
    return html.unescape(match.group(1)).strip() if match else ""


def _sanitize_hainan_snapshot(response_text: str) -> str:
    sanitized = re.sub(r"'[0-9a-fA-F]{128,}'", "'[REDACTED_OPAQUE]'", response_text)
    return re.sub(
        r"(?i)(name=[\"'](?:conversationid|encrypted_query|query|sessionid|token)[\"'][^>]*value=[\"'])[^\"']*",
        r"\1[REDACTED]",
        sanitized,
    )


def _looks_like_airline_challenge(response_text: str) -> bool:
    lowered = response_text.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS) or any(
        marker in response_text for marker in ("当前访问的人太多", "访问过于频繁", "安全校验失败")
    )


def _qingdao_airlines_trick_token(init_payload: dict[str, Any], now: datetime) -> str:
    values = init_payload.get("result") if isinstance(init_payload.get("result"), dict) else init_payload
    try:
        a = int(values["a"])
        b = int(values["b"])
        d = int(values["d"])
        e = int(values["e"])
        f = int(values["f"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FlightProviderError("airline_qw_public_query anonymous initialization payload is incomplete") from exc
    weekday_values = {
        0: a + b,
        1: e,
        2: a + 2,
        3: 2 * d,
        4: e,
        5: f - 1,
        6: b + 1,
    }
    token_input = f"@#{weekday_values[now.weekday()]}".encode("utf-8")
    return hashlib.md5(token_input, usedforsecurity=False).hexdigest()


def _qingdao_airlines_request_body(
    request: FlightSearchRequest,
    *,
    cookie_id: str,
    trick_token: str,
) -> dict[str, Any]:
    return {
        "isReturn": False,
        "departureDate": request.departure_date.isoformat(),
        "returnDate": "",
        "iorD": "D",
        "origName": request.origin_city_name,
        "origCode3": request.origin_iata.upper(),
        "destName": request.destination_city_name,
        "destCode3": request.destination_iata.upper(),
        "classType": "",
        "payment": "CASH",
        "openId": cookie_id,
        "trickToken": trick_token,
        "plat": "NB2C",
    }


def _parse_qingdao_airlines_payload(
    payload: dict[str, Any],
    *,
    request: FlightSearchRequest,
    evidence_id: str,
    cache_ttl_seconds: int,
    diagnostics: FlightParseDiagnostics | None = None,
) -> list[FlightOffer]:
    diagnostics = diagnostics or FlightParseDiagnostics()
    result = payload.get("result")
    raw_flights = result.get("departAVFS") if isinstance(result, dict) else None
    if not isinstance(raw_flights, list):
        return []
    offers: list[FlightOffer] = []
    for raw_flight in raw_flights:
        if not isinstance(raw_flight, dict):
            continue
        diagnostics.raw_candidate_count += 1
        flight_no = str(raw_flight.get("flightNo") or "").strip().upper()
        if not re.fullmatch(r"QW\d{3,4}[A-Z]?", flight_no):
            diagnostics.reject("FLIGHT_NUMBER_INVALID")
            continue
        origin_iata = str(raw_flight.get("departApCode3") or "").strip().upper()
        destination_iata = str(raw_flight.get("destApCode3") or "").strip().upper()
        if not _actual_airport_is_allowed(origin_iata, request, origin=True) or not _actual_airport_is_allowed(
            destination_iata, request, origin=False
        ):
            diagnostics.reject(
                "FLIGHT_AIRPORT_UNRESOLVED"
                if not re.fullmatch(r"[A-Z]{3}", origin_iata)
                or not re.fullmatch(r"[A-Z]{3}", destination_iata)
                else "FLIGHT_AIRPORT_OUT_OF_SCOPE"
            )
            continue
        departure_date = _date_from_value(raw_flight.get("flightDate"), request.departure_date)
        arrival_date = _date_from_value(raw_flight.get("destDate"), departure_date)
        departure_at = _parse_datetime(raw_flight.get("departTime"), departure_date)
        arrival_at = _parse_datetime(raw_flight.get("destTime"), arrival_date)
        if departure_at is None or arrival_at is None:
            diagnostics.reject("FLIGHT_TIME_INVALID")
            continue
        if arrival_at <= departure_at:
            arrival_at += timedelta(days=1)
        cabins = _qingdao_airlines_cabin_options(raw_flight, flight_no=flight_no, evidence_id=evidence_id)
        if not cabins:
            diagnostics.reject("FLIGHT_CABIN_UNAVAILABLE")
            continue
        selected = min(cabins, key=lambda cabin: cabin.price.amount_minor)
        offers.append(
            FlightOffer(
                offer_id=f"qingdao_{flight_no.lower()}_{departure_date.isoformat()}",
                source="QINGDAO_AIRLINES_PUBLIC_FRONTEND",
                total_price=selected.price,
                currency=selected.price.currency,
                segments=[
                    FlightOfferSegment(
                        carrier_code="QW",
                        flight_number=flight_no[2:],
                        origin_iata=origin_iata,
                        destination_iata=destination_iata,
                        departure_at=departure_at,
                        arrival_at=arrival_at,
                        duration=str(raw_flight.get("duration") or "") or None,
                    )
                ],
                validating_airline_codes=["QW"],
                raw_offer={
                    "flight_number": flight_no,
                    "route": raw_flight.get("flight"),
                    "minimum_price": raw_flight.get("minimumPrice"),
                    "evidence_id": evidence_id,
                },
                data_source=flight_data_source_metadata(
                    QINGDAO_AIRLINES_SOURCE_ID,
                    QingdaoAirlinesPublicQueryProvider.source_name,
                    cache_hit=False,
                    cache_ttl_seconds=cache_ttl_seconds,
                    evidence_id=evidence_id,
                ),
                cabin_options=cabins,
                evidence_id=evidence_id,
            )
        )
    return offers


def _qingdao_airlines_cabin_options(
    raw_flight: dict[str, Any],
    *,
    flight_no: str,
    evidence_id: str,
) -> list[FlightOfferCabinOption]:
    fares = raw_flight.get("fares")
    if not isinstance(fares, list):
        return []
    cabins: list[FlightOfferCabinOption] = []
    for index, fare in enumerate(fares, start=1):
        if not isinstance(fare, dict):
            continue
        price = _money_from_value(fare.get("price_ad"))
        if price is None or price.amount_minor <= 0:
            continue
        seat_value = str(fare.get("avTkt") or "").strip().upper()
        remaining = _optional_int(seat_value) if seat_value != "A" else None
        if remaining == 0:
            continue
        availability = "LIMITED" if remaining is not None and remaining > 0 else "AVAILABLE"
        fare_code = str(fare.get("name") or f"fare_{index}").strip().upper()
        cabin_type = _qingdao_airlines_cabin_type(fare)
        option_token = _normalize_option_token(f"{fare_code}_{cabin_type}_{index}_{price.amount_minor}")
        cabins.append(
            FlightOfferCabinOption(
                option_id=f"qingdao_{flight_no.lower()}_{option_token}",
                cabin_type=cabin_type,
                price=price,
                availability=availability,
                source_option_version=f"qingdao_{flight_no}_{evidence_id}_{option_token}",
                inventory_evidence=f"public_response_avTkt={seat_value or 'unknown'}",
                remaining_count=remaining if remaining is not None and remaining > 0 else None,
            )
        )
    return cabins


def _qingdao_airlines_cabin_type(fare: dict[str, Any]) -> str:
    raw_type = str(fare.get("clazzType") or "").strip().upper()
    if raw_type in {"FIRST", "F"}:
        return "FIRST"
    if raw_type in {"BUSINESS", "BUS", "C"}:
        return "BUSINESS"
    if raw_type in {"PREMIUM_ECONOMY", "PREMIUM", "W"}:
        return "PREMIUM_ECONOMY"
    return "ECONOMY"


def _date_from_value(value: Any, fallback: date) -> date:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return fallback


def _parse_public_airline_payload(
    payload: dict[str, Any],
    *,
    request: FlightSearchRequest,
    source_id: str,
    source_name: str,
    allowed_carriers: tuple[str, ...],
    evidence_id: str,
    cache_ttl_seconds: int,
) -> list[FlightOffer]:
    raw_offers = _extract_offer_items(payload)
    offers: list[FlightOffer] = []
    for index, item in enumerate(raw_offers, start=1):
        if not isinstance(item, dict):
            continue
        segments = _segments_from_offer(item, request)
        if not segments:
            continue
        if request.non_stop is True and len(segments) != 1:
            continue
        if allowed_carriers and not any(segment.carrier_code.upper() in allowed_carriers for segment in segments):
            continue
        cabins = _cabin_options_from_offer(item, source_id=source_id, source_name=source_name, evidence_id=evidence_id, cache_ttl_seconds=cache_ttl_seconds)
        if not cabins:
            continue
        selected = min(cabins, key=lambda cabin: cabin.price.amount_minor)
        offer_id = str(item.get("offer_id") or item.get("offerId") or item.get("id") or f"{source_id}_{request.departure_date.isoformat()}_{index}")
        data_source = flight_data_source_metadata(source_id, source_name, cache_hit=False, cache_ttl_seconds=cache_ttl_seconds, evidence_id=evidence_id)
        normalized = FlightOffer(
            offer_id=offer_id,
            source=str(item.get("source") or source_id),
            total_price=selected.price,
            currency=selected.price.currency,
            segments=segments,
            validating_airline_codes=_validating_airlines(item, segments),
            raw_offer={**item, "evidence_id": evidence_id},
            data_source=data_source,
            cabin_options=cabins,
            evidence_id=evidence_id,
        )
        offers.append(normalized)
    return offers


def _public_airline_raw_candidate_count(payload: dict[str, Any]) -> int:
    return len(_extract_offer_items(payload))


def _actual_airport_is_allowed(
    airport_iata: str,
    request: FlightSearchRequest,
    *,
    origin: bool,
) -> bool:
    normalized = airport_iata.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", normalized):
        return False
    allowed = (
        request.allowed_origin_airport_iatas
        if origin
        else request.allowed_destination_airport_iatas
    )
    normalized_allowed = {code.strip().upper() for code in allowed if code}
    if normalized_allowed:
        return normalized in normalized_allowed
    if request.query_scope == "AIRPORT":
        expected = request.origin_iata if origin else request.destination_iata
        return normalized == expected.strip().upper()
    return True


def _log_flight_parse_diagnostics(
    *,
    source_id: str,
    evidence_id: str,
    raw_candidate_count: int,
    offers: list[FlightOffer],
    rejected_counts: dict[str, int],
) -> None:
    actual_airports = sorted(
        {
            airport
            for offer in offers
            for segment in offer.segments
            for airport in (segment.origin_iata, segment.destination_iata)
        }
    )
    logger.info(
        "flight_parser_diagnostics source_id=%s parser_version=%s evidence_id=%s "
        "raw_candidate_count=%s offer_count=%s actual_airports=%s rejected_counts=%s",
        source_id,
        "flight_scope_v1",
        evidence_id,
        raw_candidate_count,
        len(offers),
        ",".join(actual_airports),
        json.dumps(rejected_counts, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    )


def _extract_offer_items(payload: dict[str, Any]) -> list[Any]:
    if isinstance(payload.get("offers"), list):
        return payload["offers"]
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("offers", "flightOffers", "flights", "itineraries"):
            if isinstance(data.get(key), list):
                return data[key]
    for key in ("flightOffers", "flights", "itineraries", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def _segments_from_offer(item: dict[str, Any], request: FlightSearchRequest) -> list[FlightOfferSegment]:
    raw_segments: list[Any] = []
    if isinstance(item.get("segments"), list):
        raw_segments = item["segments"]
    elif isinstance(item.get("legs"), list):
        raw_segments = item["legs"]
    elif isinstance(item.get("itineraries"), list):
        for itinerary in item["itineraries"]:
            if isinstance(itinerary, dict) and isinstance(itinerary.get("segments"), list):
                raw_segments.extend(itinerary["segments"])
    if not raw_segments:
        raw_segments = [item]

    segments: list[FlightOfferSegment] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        departure = raw.get("departure") if isinstance(raw.get("departure"), dict) else {}
        arrival = raw.get("arrival") if isinstance(raw.get("arrival"), dict) else {}
        carrier_code = str(raw.get("carrier_code") or raw.get("carrierCode") or raw.get("airlineCode") or raw.get("marketingCarrier") or item.get("carrier_code") or item.get("carrierCode") or "").strip()
        flight_number = str(raw.get("flight_number") or raw.get("flightNumber") or raw.get("number") or raw.get("flightNo") or item.get("flight_number") or item.get("flightNumber") or "").strip()
        if not carrier_code:
            match = re.fullmatch(r"([A-Za-z]{2})(\d+[A-Za-z]?)", flight_number)
            if match:
                carrier_code = match.group(1).upper()
                flight_number = match.group(2)
        elif re.fullmatch(r"[A-Za-z]{2}\d+[A-Za-z]?", flight_number):
            flight_number = flight_number[len(carrier_code) :]
        origin_iata = str(raw.get("origin_iata") or raw.get("originIata") or raw.get("origin") or departure.get("iataCode") or "").strip().upper()
        destination_iata = str(raw.get("destination_iata") or raw.get("destinationIata") or raw.get("destination") or arrival.get("iataCode") or "").strip().upper()
        departure_at = _parse_datetime(raw.get("departure_at") or raw.get("departureAt") or raw.get("departureTime") or departure.get("at"), request.departure_date)
        arrival_at = _parse_datetime(raw.get("arrival_at") or raw.get("arrivalAt") or raw.get("arrivalTime") or arrival.get("at"), request.departure_date)
        if (
            not carrier_code
            or not flight_number
            or not re.fullmatch(r"[A-Z]{3}", origin_iata)
            or not re.fullmatch(r"[A-Z]{3}", destination_iata)
        ):
            continue
        segments.append(
            FlightOfferSegment(
                carrier_code=carrier_code,
                flight_number=flight_number,
                origin_iata=origin_iata,
                destination_iata=destination_iata,
                departure_at=departure_at,
                arrival_at=arrival_at,
                duration=str(raw.get("duration") or item.get("duration") or "") or None,
            )
        )
    if not segments:
        return []
    if not _actual_airport_is_allowed(segments[0].origin_iata, request, origin=True):
        return []
    if not _actual_airport_is_allowed(segments[-1].destination_iata, request, origin=False):
        return []
    return segments


def _cabin_options_from_offer(
    item: dict[str, Any],
    *,
    source_id: str,
    source_name: str,
    evidence_id: str,
    cache_ttl_seconds: int,
) -> list[FlightOfferCabinOption]:
    raw_cabins = item.get("cabin_options") or item.get("cabinOptions") or item.get("cabins") or item.get("fareOptions") or []
    if not isinstance(raw_cabins, list):
        raw_cabins = []
    if not raw_cabins:
        raw_cabins = [item]

    cabins: list[FlightOfferCabinOption] = []
    for index, raw in enumerate(raw_cabins, start=1):
        if not isinstance(raw, dict):
            continue
        availability = _availability_from_value(raw.get("availability") or raw.get("available") or raw.get("inventoryStatus") or item.get("availability") or item.get("available"))
        if availability not in {"AVAILABLE", "LIMITED"}:
            continue
        price = _money_from_value(raw.get("price") or raw.get("totalPrice") or raw.get("total_price") or item.get("price") or item.get("totalPrice") or item.get("total_price"))
        if price is None or price.amount_minor <= 0:
            continue
        remaining_count = _optional_int(raw.get("remaining_count") or raw.get("remainingCount") or raw.get("remainingSeats") or item.get("remainingSeats"))
        cabin_type = str(raw.get("cabin_type") or raw.get("cabinType") or raw.get("cabin") or item.get("cabinType") or "ECONOMY").strip() or "ECONOMY"
        if remaining_count is not None and remaining_count <= 0:
            continue
        option_id = str(raw.get("option_id") or raw.get("optionId") or f"cabin_{_normalize_option_token(cabin_type)}_{index}")
        source_option_version = str(raw.get("source_option_version") or raw.get("sourceOptionVersion") or f"{source_id}_{evidence_id}_{index}")
        cabins.append(
            FlightOfferCabinOption(
                option_id=option_id,
                cabin_type=cabin_type,
                price=price,
                availability=availability,
                source_option_version=source_option_version,
                inventory_evidence=str(raw.get("inventory_evidence") or raw.get("inventoryEvidence") or raw.get("availabilityText") or availability),
                remaining_count=remaining_count,
            )
        )
    return cabins


def _validating_airlines(item: dict[str, Any], segments: list[FlightOfferSegment]) -> list[str]:
    value = item.get("validating_airline_codes") or item.get("validatingAirlineCodes")
    if isinstance(value, list):
        return [str(code) for code in value if code]
    return sorted({segment.carrier_code for segment in segments if segment.carrier_code})


def _availability_from_value(value: Any) -> str:
    if isinstance(value, bool):
        return "AVAILABLE" if value else "NO_TICKET"
    text = str(value or "").strip().lower()
    if text in {"available", "true", "yes", "y", "有", "可售", "有票"}:
        return "AVAILABLE"
    if text in {"limited", "low", "few", "少", "紧张"} or re.search(r"(only|剩余|仅剩)\s*\d+", text):
        return "LIMITED"
    return "NO_TICKET"


def _money_from_value(value: Any) -> Money | None:
    if value is None:
        return None
    if isinstance(value, Money):
        return value
    if isinstance(value, dict):
        currency = str(value.get("currency") or "CNY")
        total = value.get("amount_minor")
        if total is not None:
            return money(int(total), currency=currency)
        total = value.get("total") or value.get("grandTotal") or value.get("amount") or value.get("value")
        if total is None:
            return None
        return _price_to_money(str(total), currency)
    if isinstance(value, (int, float)):
        return _price_to_money(str(value), "CNY")
    text = str(value).strip()
    if not text:
        return None
    currency = "CNY"
    if "USD" in text.upper():
        currency = "USD"
    match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if not match:
        return None
    return _price_to_money(match.group(1), currency)


def _response_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except (ValueError, AttributeError):
        pass
    text = _response_text(response)
    match = re.search(r'<script[^>]+id=["\']flight-offers-json["\'][^>]*>(.*?)</script>', text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        decoded = html.unescape(match.group(1)).strip()
        payload = json.loads(decoded)
        if isinstance(payload, dict):
            return payload
    raise FlightProviderError("public airline response did not contain supported JSON payload")


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    try:
        payload = response.json()
        return json.dumps(payload, ensure_ascii=False)
    except (ValueError, AttributeError):
        return ""


_SENSITIVE_SNAPSHOT_KEYS = re.compile(
    r"(?:authorization|cookie|set-cookie|token|access[_-]?token|refresh[_-]?token|session|sessionid|csrf|signature|sign|enc|api[_-]?key)",
    flags=re.IGNORECASE,
)
_CHALLENGE_MARKERS = (
    "captcha",
    "geetest",
    "cf-chl-",
    "hcaptcha",
    "recaptcha",
    "\u9a8c\u8bc1\u7801",
    "\u4eba\u673a\u9a8c\u8bc1",
)


def redact_flight_snapshot(payload_text: str) -> str:
    """Remove credentials and dynamic session material before persistence."""

    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        payload = None
    if payload is not None:
        return json.dumps(_redact_snapshot_value(payload), ensure_ascii=False, separators=(",", ":"))

    redacted = payload_text
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"'<>]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\r\n<]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)([?&](?:token|access_token|refresh_token|session|sessionid|csrf|signature|sign|enc|api_key)=)[^&#\s\"'<>]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([\"'](?:token|access_token|refresh_token|session|sessionid|csrf|signature|sign|enc|api_key)[\"']\s*:\s*[\"'])[^\"']*",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted


def _redact_snapshot_value(value: Any, key: str | None = None) -> Any:
    if key and _SENSITIVE_SNAPSHOT_KEYS.fullmatch(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact_snapshot_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_snapshot_value(item) for item in value]
    if isinstance(value, str):
        return redact_flight_snapshot(value) if re.search(r"https?://|authorization|cookie", value, flags=re.IGNORECASE) else value
    return value


def _request_key_fingerprint(request_key: str) -> str:
    return f"sha256:{hashlib.sha256(request_key.encode('utf-8')).hexdigest()[:24]}"


def _raise_for_airline_risk_response(response: Any, *, source_id: str) -> None:
    status_code = getattr(response, "status_code", None)
    if status_code == 429:
        retry_after = str(getattr(response, "headers", {}).get("retry-after", "")).strip()
        suffix = f"; retry-after={retry_after}" if retry_after else ""
        raise FlightProviderError(f"{source_id} rate limited (HTTP 429){suffix}")
    lowered = _response_text(response).lower()
    marker = next((item for item in _CHALLENGE_MARKERS if item in lowered), None)
    if marker:
        raise FlightProviderError(f"{source_id} anti-bot challenge detected; automated bypass is forbidden")


def _base_url_matches_allowed_hosts(base_url: str, allowed_hosts: tuple[str, ...]) -> bool:
    parsed = urlparse(base_url)
    if parsed.scheme.lower() != "https":
        return False
    hostname = (parsed.hostname or "").lower().strip(".")
    for allowed_host in allowed_hosts:
        normalized = allowed_host.lower().strip(".")
        if hostname == normalized or hostname.endswith(f".{normalized}"):
            return True
    return False


def _cache_key(source_id: str, request: FlightSearchRequest) -> str:
    return ":".join(
        [
            source_id,
            request.query_scope,
            request.origin_iata.upper(),
            request.destination_iata.upper(),
            (request.origin_city_code or "").upper(),
            (request.destination_city_code or "").upper(),
            ",".join(_normalized_iata_tuple(request.allowed_origin_airport_iatas)),
            ",".join(_normalized_iata_tuple(request.allowed_destination_airport_iatas)),
            request.origin_city_name or "",
            request.destination_city_name or "",
            request.departure_date.isoformat(),
            str(request.adults),
            request.currency_code.upper(),
            "any" if request.non_stop is None else str(request.non_stop).lower(),
        ]
    )


def _cache_get(key: str, ttl_seconds: int) -> list[FlightOffer] | None:
    if ttl_seconds <= 0:
        return None
    item = _SEARCH_CACHE.get(key)
    if item is None:
        return None
    expires_at, offers = item
    if expires_at <= _monotonic():
        _SEARCH_CACHE.pop(key, None)
        return None
    return offers


def _cache_set(key: str, offers: list[FlightOffer], ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    _SEARCH_CACHE[key] = (_monotonic() + ttl_seconds, offers)


def _offer_with_cache_metadata(offer: FlightOffer, *, cache_hit: bool, ttl_seconds: int | None) -> FlightOffer:
    data_source = flight_data_source_metadata(offer.data_source.source_id, offer.data_source.source_name, cache_hit=cache_hit, cache_ttl_seconds=ttl_seconds, evidence_id=offer.evidence_id)
    cabins = [cabin for cabin in offer.cabin_options]
    return FlightOffer(
        offer_id=offer.offer_id,
        source=offer.source,
        total_price=offer.total_price,
        currency=offer.currency,
        segments=offer.segments,
        validating_airline_codes=offer.validating_airline_codes,
        raw_offer=offer.raw_offer,
        data_source=data_source,
        cabin_options=cabins,
        evidence_id=offer.evidence_id,
    )


def _respect_provider_rate_limit(source_id: str, interval_seconds: float) -> None:
    if interval_seconds <= 0:
        return
    with _RATE_LIMIT_LOCK:
        now = _monotonic()
        previous = _LAST_PROVIDER_CALL_AT.get(source_id)
        if previous is not None:
            wait_seconds = interval_seconds - (now - previous)
            if wait_seconds > 0:
                logger.info("flight_provider_rate_limit_wait source_id=%s wait_seconds=%.3f", source_id, wait_seconds)
                _sleep(wait_seconds)
                now = _monotonic()
        _LAST_PROVIDER_CALL_AT[source_id] = now


def _init_flight_snapshot_store(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flight_raw_snapshots (
              snapshot_id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              request_key TEXT NOT NULL,
              payload_text TEXT NOT NULL,
              content_type TEXT,
              fetched_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flight_canonical_offers (
              offer_id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              request_key TEXT NOT NULL,
              offer_json TEXT NOT NULL,
              indexed_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            )
            """
        )


def _offer_to_json(offer: FlightOffer) -> str:
    return json.dumps(
        {
            "offer_id": offer.offer_id,
            "source": offer.source,
            "total_price": offer.total_price.model_dump(),
            "currency": offer.currency,
            "segments": [segment.__dict__ for segment in offer.segments],
            "validating_airline_codes": offer.validating_airline_codes,
            "cabin_options": [
                {
                    "option_id": cabin.option_id,
                    "cabin_type": cabin.cabin_type,
                    "price": cabin.price.model_dump(),
                    "availability": cabin.availability,
                    "source_option_version": cabin.source_option_version,
                    "inventory_evidence": cabin.inventory_evidence,
                    "remaining_count": cabin.remaining_count,
                }
                for cabin in offer.cabin_options
            ],
            "evidence_id": offer.evidence_id,
        },
        ensure_ascii=False,
        default=str,
    )


def _parse_datetime(value: Any, departure_date: date | None = None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text) and departure_date is not None:
        if text.count(":") == 1:
            text = f"{text}:00"
        return datetime.fromisoformat(f"{departure_date.isoformat()}T{text}").replace(tzinfo=SHANGHAI_TZ)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _price_to_money(total: str, currency: str) -> Money:
    try:
        decimal_value = Decimal(str(total))
    except InvalidOperation as exc:
        raise ValueError("invalid flight price") from exc
    amount_minor = int((decimal_value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    display_value = (Decimal(abs(amount_minor)) / Decimal("100")).quantize(Decimal("0.01"))
    return Money(
        amount_minor=amount_minor,
        currency=currency,
        scale=2,
        is_estimated=False,
        display_text=f"{currency} {display_value}",
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None


def _normalize_option_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "option"
