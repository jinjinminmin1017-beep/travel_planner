from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.data_sources.config_loader import load_data_source_configs, public_airline_allowed_hosts
from app.models.schemas import CacheMetadata, DataSourceMetadata, DataSourceType, Money, money, now_timepoint

logger = logging.getLogger("app.flight")


class FlightProviderError(RuntimeError):
    pass


PUBLIC_AIRLINE_SOURCE_IDS = (
    "airline_mu_public_query",
    "airline_cz_public_query",
    "airline_sc_public_query",
)
DEFAULT_AIRLINE_PUBLIC_SEARCH_PATH = "/api/flight/search"
DEFAULT_AIRLINE_PUBLIC_USER_AGENT = "AITravelPlanner/0.1 public-airline-query"
DEFAULT_FLIGHT_CACHE_TTL_SECONDS = 60
SHANGHAI_TZ = timezone(timedelta(hours=8))

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
    adults: int = 1
    currency_code: str = "CNY"
    max_results: int = 5
    non_stop: bool | None = None


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


@dataclass(frozen=True)
class FlightProviderSearchResult:
    offers: list[FlightOffer]
    attempted_source_ids: list[str]
    failure_message: str | None = None


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
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.FLIGHT,
        authority_level="A" if source_id in PUBLIC_AIRLINE_SOURCE_IDS else "B",
        source_priority=10 if source_id in PUBLIC_AIRLINE_SOURCE_IDS else None,
        source_region="CN" if source_id in PUBLIC_AIRLINE_SOURCE_IDS else None,
        api_version=f"public_frontend_snapshot:{evidence_id}" if evidence_id else None,
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
        cache_ttl_seconds=cache_ttl_seconds,
        sla_level="PUBLIC_AIRLINE_FRONTEND_QUERY" if source_id in PUBLIC_AIRLINE_SOURCE_IDS else "PUBLIC_READ_ONLY_RATE_LIMITED",
        cache_metadata=CacheMetadata(cacheable=True, cache_ttl_seconds=cache_ttl_seconds, cache_hit=cache_hit),
    )


class OfficialAirlinePublicQueryProvider:
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
    ) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.allowed_carriers = tuple(code.upper() for code in allowed_carriers)
        self.allowed_hosts = tuple(host.lower().strip(".") for host in (allowed_hosts or public_airline_allowed_hosts(source_id)))
        self.base_url = (base_url or _source_env(source_id, "BASE_URL") or "").rstrip("/")
        self.search_path = search_path or _source_env(source_id, "SEARCH_PATH") or DEFAULT_AIRLINE_PUBLIC_SEARCH_PATH
        self.user_agent = user_agent or _source_env(source_id, "USER_AGENT") or DEFAULT_AIRLINE_PUBLIC_USER_AGENT
        self.cache_ttl_seconds = cache_ttl_seconds if cache_ttl_seconds is not None else _public_query_cache_ttl_seconds(source_id)
        self.client = client or httpx.Client(timeout=_provider_timeout_seconds(), follow_redirects=False, headers=self._headers())

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        if not self.base_url:
            raise FlightProviderError(f"{self.source_id} base URL is not configured")
        if not _base_url_matches_allowed_hosts(self.base_url, self.allowed_hosts):
            raise FlightProviderError(f"{self.source_id} base URL is outside the source allowlist")

        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            logger.info("flight_public_cache_hit source_id=%s cache_key=%s offer_count=%s", self.source_id, cache_key, len(cached))
            return [_offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds) for offer in cached]

        _respect_provider_rate_limit(self.source_id)
        endpoint = f"{self.base_url}{self.search_path if self.search_path.startswith('/') else '/' + self.search_path}"
        logger.info(
            "flight_public_search_start source_id=%s origin_iata=%s destination_iata=%s departure_date=%s",
            self.source_id,
            request.origin_iata,
            request.destination_iata,
            request.departure_date.isoformat(),
        )
        response = self.client.get(
            endpoint,
            params={
                "origin": request.origin_iata,
                "destination": request.destination_iata,
                "departureDate": request.departure_date.isoformat(),
                "adults": request.adults,
                "currency": request.currency_code,
                **({"nonStop": str(request.non_stop).lower()} if request.non_stop is not None else {}),
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        payload = _response_payload(response)
        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=_response_text(response),
            content_type=str(response.headers.get("content-type", "")) if hasattr(response, "headers") else "",
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
        offers = sorted(offers, key=lambda offer: offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ))
        offers = offers[: max(1, request.max_results)]
        if offers:
            _cache_set(cache_key, offers, self.cache_ttl_seconds)
            save_flight_canonical_offers(source_id=self.source_id, request_key=cache_key, offers=offers, ttl_seconds=self.cache_ttl_seconds)
            logger.info("flight_public_search_success source_id=%s offer_count=%s", self.source_id, len(offers))
            return offers
        logger.info("flight_public_search_empty source_id=%s", self.source_id)
        return []

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }


class OpenSkyStatesProvider:
    source_id = "opensky_states"

    def __init__(self, client: httpx.Client | None = None, base_url: str | None = None) -> None:
        self.client = client or httpx.Client(timeout=10.0)
        self.base_url = (base_url or os.getenv("OPENSKY_BASE_URL") or "https://opensky-network.org").rstrip("/")

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
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    providers: list[FlightOfferProvider] = []
    source_names = {
        "airline_mu_public_query": ("China Eastern Official Public Flight Query", ("MU", "FM")),
        "airline_cz_public_query": ("China Southern Official Public Flight Query", ("CZ",)),
        "airline_sc_public_query": ("Shandong Airlines Official Public Flight Query", ("SC",)),
    }
    for source_id in PUBLIC_AIRLINE_SOURCE_IDS:
        config = configs.get(source_id)
        if not config or not config.enabled or config.license_status != "APPROVED":
            continue
        source_name, carriers = source_names[source_id]
        providers.append(OfficialAirlinePublicQueryProvider(source_id=source_id, source_name=source_name, allowed_carriers=carriers))
    return providers


def build_enabled_flight_state_providers(environment: str | None = None) -> list[FlightStateProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("opensky_states")
    if config and config.enabled and config.license_status == "APPROVED":
        return [OpenSkyStatesProvider()]
    return []


def search_flight_offers_with_enabled_provider(request: FlightSearchRequest, environment: str | None = None) -> list[FlightOffer]:
    return search_flight_offers_with_enabled_provider_result(request, environment).offers


def search_flight_offers_with_enabled_provider_result(request: FlightSearchRequest, environment: str | None = None) -> FlightProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    providers = build_enabled_flight_providers(environment)
    if not providers:
        return FlightProviderSearchResult(offers=[], attempted_source_ids=list(PUBLIC_AIRLINE_SOURCE_IDS), failure_message="no enabled public airline flight provider")
    for provider in providers:
        attempted_source_ids.append(provider.source_id)
        try:
            offers = provider.search_offers(request)
            if offers:
                return FlightProviderSearchResult(offers=offers, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
        except (httpx.HTTPError, FlightProviderError, ValueError, KeyError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
            logger.warning("flight_provider_search_failure source_id=%s error=%s", provider.source_id, exc)
    return FlightProviderSearchResult(offers=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


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


def save_flight_raw_snapshot(*, source_id: str, request_key: str, payload_text: str, content_type: str) -> str:
    snapshot_id = f"fltraw_{uuid4().hex[:12]}"
    if _snapshot_backend_disabled():
        return snapshot_id
    _init_flight_snapshot_store()
    with sqlite3.connect(_flight_snapshot_path()) as conn:
        conn.execute(
            """
            INSERT INTO flight_raw_snapshots(snapshot_id, source_id, request_key, payload_text, content_type, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (snapshot_id, source_id, request_key, payload_text, content_type, datetime.now(timezone.utc).isoformat()),
        )
    return snapshot_id


def save_flight_canonical_offers(*, source_id: str, request_key: str, offers: list[FlightOffer], ttl_seconds: int) -> None:
    if _snapshot_backend_disabled():
        return
    _init_flight_snapshot_store()
    indexed_at = datetime.now(timezone.utc)
    expires_at = indexed_at + timedelta(seconds=max(0, ttl_seconds))
    with sqlite3.connect(_flight_snapshot_path()) as conn:
        for offer in offers:
            conn.execute(
                """
                INSERT OR REPLACE INTO flight_canonical_offers(offer_id, source_id, request_key, offer_json, indexed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (offer.offer_id, source_id, request_key, _offer_to_json(offer), indexed_at.isoformat(), expires_at.isoformat()),
            )


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
        origin_iata = str(raw.get("origin_iata") or raw.get("originIata") or raw.get("origin") or departure.get("iataCode") or request.origin_iata).strip().upper()
        destination_iata = str(raw.get("destination_iata") or raw.get("destinationIata") or raw.get("destination") or arrival.get("iataCode") or request.destination_iata).strip().upper()
        departure_at = _parse_datetime(raw.get("departure_at") or raw.get("departureAt") or raw.get("departureTime") or departure.get("at"), request.departure_date)
        arrival_at = _parse_datetime(raw.get("arrival_at") or raw.get("arrivalAt") or raw.get("arrivalTime") or arrival.get("at"), request.departure_date)
        if not carrier_code or not flight_number or not origin_iata or not destination_iata:
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


def _source_env(source_id: str, suffix: str) -> str | None:
    return os.getenv(f"TRAVEL_SOURCE_{source_id.upper()}_{suffix}")


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
            request.origin_iata.upper(),
            request.destination_iata.upper(),
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


def _public_query_cache_ttl_seconds(source_id: str) -> int:
    return int(_source_env(source_id, "CACHE_TTL_SECONDS") or str(DEFAULT_FLIGHT_CACHE_TTL_SECONDS))


def _provider_timeout_seconds() -> float:
    return float(os.getenv("TRAVEL_PROVIDER_TIMEOUT_SECONDS", "10"))


def _respect_provider_rate_limit(source_id: str) -> None:
    interval_seconds = _provider_min_interval_seconds(source_id)
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


def _provider_min_interval_seconds(source_id: str) -> float:
    env_override = _source_env(source_id, "MIN_INTERVAL_SECONDS")
    if env_override:
        return _safe_float(env_override, 1.0)
    configs = {config.source_id: config for config in load_data_source_configs()}
    config = configs.get(source_id)
    if config and config.qps_limit > 0:
        return 1.0 / config.qps_limit
    return 1.0


def _init_flight_snapshot_store() -> None:
    path = _flight_snapshot_path()
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


def _flight_snapshot_path() -> Path:
    return Path(os.getenv("TRAVEL_FLIGHT_SNAPSHOT_SQLITE_PATH", "logs/flight_harvest.sqlite3"))


def _snapshot_backend_disabled() -> bool:
    return os.getenv("TRAVEL_FLIGHT_SNAPSHOT_BACKEND", "sqlite").lower() == "disabled"


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
    amount_minor = int(round(float(total) * 100))
    value = abs(amount_minor) / 100
    return Money(amount_minor=amount_minor, currency=currency, scale=2, is_estimated=False, display_text=f"{currency} {value:.2f}")


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


def _safe_float(value: str, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except ValueError:
        return fallback
