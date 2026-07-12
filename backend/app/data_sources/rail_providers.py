from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import load_data_source_configs
from app.models.schemas import CacheMetadata, DataSourceMetadata, DataSourceType, Money, SeatOption, money, now_timepoint

logger = logging.getLogger("app.rail")


class RailProviderError(RuntimeError):
    pass


BASE_DIR = Path(__file__).resolve().parent
TRANSPORT_NODES_PATH = BASE_DIR.parent / "data" / "transport_nodes.json"
DEFAULT_12306_BASE_URL = "https://kyfw.12306.cn"
DEFAULT_12306_USER_AGENT = "AITravelPlanner/0.1 public-12306-query"
SHANGHAI_TZ = timezone(timedelta(hours=8))

_RATE_LIMIT_LOCK = threading.Lock()
_LAST_PROVIDER_CALL_AT: dict[str, float] = {}
_SEARCH_CACHE: dict[str, tuple[float, list["RailOffer"]]] = {}
_monotonic = time.monotonic
_sleep = time.sleep


@dataclass(frozen=True)
class RailSearchRequest:
    train_number: str
    origin_station: str
    destination_station: str
    departure_date: date


@dataclass(frozen=True)
class RailOffer:
    train_number: str
    origin_station: str
    destination_station: str
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int
    stop_sequence: list[str]
    seat_options: list[SeatOption]
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class RailProviderSearchResult:
    offers: list[RailOffer]
    attempted_source_ids: list[str]
    failure_message: str | None = None


class RailProvider(Protocol):
    source_id: str

    def search_offers(self, request: RailSearchRequest) -> list[RailOffer]:
        ...


class Official12306RailProvider:
    source_id = "rail_12306_public_query"

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str | None = None,
        user_agent: str | None = None,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_BASE_URL") or DEFAULT_12306_BASE_URL).rstrip("/")
        self.user_agent = user_agent or os.getenv("TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_USER_AGENT") or DEFAULT_12306_USER_AGENT
        self.cache_ttl_seconds = cache_ttl_seconds if cache_ttl_seconds is not None else _public_query_cache_ttl_seconds()
        self.client = client or httpx.Client(timeout=10.0, follow_redirects=True, headers=self._headers())

    def search_offers(self, request: RailSearchRequest) -> list[RailOffer]:
        logger.info(
            "rail_12306_search_start source_id=%s origin_station=%s destination_station=%s departure_date=%s train_number=%s",
            self.source_id,
            request.origin_station,
            request.destination_station,
            request.departure_date.isoformat(),
            request.train_number or "",
        )
        origin_code = station_code_for_name(request.origin_station)
        destination_code = station_code_for_name(request.destination_station)
        logger.info(
            "rail_12306_station_code_lookup source_id=%s origin_station=%s origin_code_present=%s destination_station=%s destination_code_present=%s",
            self.source_id,
            request.origin_station,
            bool(origin_code),
            request.destination_station,
            bool(destination_code),
        )
        if not origin_code or not destination_code:
            missing = request.origin_station if not origin_code else request.destination_station
            logger.warning("rail_12306_station_code_missing source_id=%s missing_station=%s", self.source_id, missing)
            raise RailProviderError(f"12306 station code missing for {missing}")

        cache_key = f"{request.departure_date.isoformat()}:{origin_code}:{destination_code}:{request.train_number.strip().upper()}"
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            logger.info(
                "rail_12306_cache_hit source_id=%s cache_key=%s ttl_seconds=%s offer_count=%s",
                self.source_id,
                cache_key,
                self.cache_ttl_seconds,
                len(cached),
            )
            return [_offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds) for offer in cached]
        logger.info("rail_12306_cache_miss source_id=%s cache_key=%s ttl_seconds=%s", self.source_id, cache_key, self.cache_ttl_seconds)

        self._ensure_public_query_session()
        payload = self._query_left_tickets(request, origin_code, destination_code)
        result = (payload.get("data") or {}).get("result") or []
        station_map = (payload.get("data") or {}).get("map") or {}
        if not isinstance(result, list):
            raise RailProviderError("12306 public query response has invalid result payload")
        if not isinstance(station_map, dict):
            station_map = {}
        logger.info(
            "rail_12306_response_received source_id=%s row_count=%s station_map_count=%s",
            self.source_id,
            len(result),
            len(station_map),
        )

        errors: list[str] = []
        offers: list[RailOffer] = []
        for raw_item in result:
            raw_text = str(raw_item or "")
            if request.train_number:
                row_train_number = _train_number_from_12306_row(raw_text)
                if row_train_number and row_train_number.upper() != request.train_number.strip().upper():
                    continue
            try:
                offer = self._parse_offer(raw_text, request, station_map)
            except RailProviderError as exc:
                errors.append(str(exc))
                continue
            if request.train_number and offer.train_number.upper() != request.train_number.strip().upper():
                continue
            offers.append(offer)

        offers = sorted(offers, key=lambda offer: offer.departure_at)
        if offers:
            _cache_set(cache_key, offers, self.cache_ttl_seconds)
            logger.info(
                "rail_12306_search_success source_id=%s cache_key=%s offer_count=%s first_train=%s",
                self.source_id,
                cache_key,
                len(offers),
                offers[0].train_number,
            )
            return offers
        if result and errors:
            logger.warning(
                "rail_12306_search_filtered_empty source_id=%s row_count=%s parse_error_count=%s first_error=%s",
                self.source_id,
                len(result),
                len(errors),
                errors[0],
            )
            raise RailProviderError("; ".join(_unique(errors)[:3]))
        logger.info("rail_12306_search_empty source_id=%s row_count=0", self.source_id)
        return []

    def _ensure_public_query_session(self) -> None:
        logger.info("rail_12306_session_init source_id=%s endpoint=/otn/leftTicket/init", self.source_id)
        response = self.client.get(f"{self.base_url}/otn/leftTicket/init", headers=self._headers())
        response.raise_for_status()
        logger.info("rail_12306_session_ready source_id=%s status_code=%s", self.source_id, getattr(response, "status_code", None))

    def _query_left_tickets(self, request: RailSearchRequest, origin_code: str, destination_code: str) -> dict[str, Any]:
        logger.info(
            "rail_12306_query_request source_id=%s endpoint=/otn/leftTicket/queryG departure_date=%s from_station_code=%s to_station_code=%s",
            self.source_id,
            request.departure_date.isoformat(),
            origin_code,
            destination_code,
        )
        response = self.client.get(
            f"{self.base_url}/otn/leftTicket/queryG",
            params={
                "leftTicketDTO.train_date": request.departure_date.isoformat(),
                "leftTicketDTO.from_station": origin_code,
                "leftTicketDTO.to_station": destination_code,
                "purpose_codes": "ADULT",
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        payload = response.json()
        logger.info(
            "rail_12306_query_response source_id=%s status_code=%s httpstatus=%s payload_status=%s",
            self.source_id,
            getattr(response, "status_code", None),
            payload.get("httpstatus") if isinstance(payload, dict) else None,
            payload.get("status") if isinstance(payload, dict) else None,
        )
        if not isinstance(payload, dict):
            raise RailProviderError("12306 public query response is not JSON object")
        if payload.get("httpstatus") not in (None, 200) or payload.get("status") is False:
            raise RailProviderError(f"12306 public query failed: {payload.get('messages') or payload.get('message') or payload.get('httpstatus')}")
        return payload

    def _parse_offer(self, raw_item: str, request: RailSearchRequest, station_map: dict[str, Any]) -> RailOffer:
        parts = raw_item.split("|")
        if len(parts) < 40:
            raise RailProviderError("12306 public query row shape changed")

        train_number = parts[3].strip()
        train_no = parts[2].strip()
        origin_code = parts[6].strip()
        destination_code = parts[7].strip()
        origin_station = str(station_map.get(origin_code) or request.origin_station)
        destination_station = str(station_map.get(destination_code) or request.destination_station)
        departure_at = _parse_train_time(request.departure_date, parts[8])
        arrival_at = _parse_train_time(request.departure_date, parts[9])
        if arrival_at < departure_at:
            arrival_at = arrival_at + timedelta(days=1)
        duration_minutes = _duration_minutes(parts[10], departure_at, arrival_at)
        data_source = rail_data_source_metadata(self.source_id, "12306 Public Ticket Query", cache_hit=False, cache_ttl_seconds=self.cache_ttl_seconds)
        prices = _parse_12306_price_blob(parts[39] if len(parts) > 39 else "")
        seats = _seat_options_from_12306_row(parts, prices, train_number or train_no, data_source)
        if not seats:
            raise RailProviderError(f"12306 public query returned no priced available seats for {train_number or train_no}")
        logger.info(
            "rail_12306_offer_parsed source_id=%s train_number=%s origin_station=%s destination_station=%s duration_minutes=%s priced_seat_count=%s",
            self.source_id,
            train_number or train_no,
            origin_station,
            destination_station,
            duration_minutes,
            len(seats),
        )
        return RailOffer(
            train_number=train_number or train_no,
            origin_station=origin_station,
            destination_station=destination_station,
            departure_at=departure_at,
            arrival_at=arrival_at,
            duration_minutes=duration_minutes,
            stop_sequence=[origin_station, destination_station],
            seat_options=seats,
            data_source=data_source,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.base_url}/otn/leftTicket/init",
            "X-Requested-With": "XMLHttpRequest",
        }


def rail_data_source_metadata(
    source_id: str,
    source_name: str,
    *,
    cache_hit: bool = False,
    cache_ttl_seconds: int | None = None,
) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.RAIL,
        authority_level="S",
        source_priority=10,
        source_region="CN",
        api_version="12306_leftTicket_queryG",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
        cache_ttl_seconds=cache_ttl_seconds,
        sla_level="PUBLIC_ANONYMOUS_QUERY",
        cache_metadata=CacheMetadata(cacheable=True, cache_ttl_seconds=cache_ttl_seconds, cache_hit=cache_hit),
    )


def build_enabled_rail_providers(environment: str | None = None) -> list[RailProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("rail_12306_public_query")
    if not config or not config.enabled or config.license_status != "APPROVED":
        logger.warning(
            "rail_provider_config_blocked source_id=rail_12306_public_query configured=%s enabled=%s license_status=%s",
            bool(config),
            config.enabled if config else None,
            config.license_status if config else None,
        )
        return []
    logger.info("rail_provider_config_enabled source_id=rail_12306_public_query qps_limit=%s", config.qps_limit)
    return [Official12306RailProvider()]


def search_rail_offers_with_enabled_provider_result(request: RailSearchRequest, environment: str | None = None) -> RailProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_rail_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            logger.info(
                "rail_provider_search_attempt source_id=%s origin_station=%s destination_station=%s departure_date=%s train_number=%s",
                provider.source_id,
                request.origin_station,
                request.destination_station,
                request.departure_date.isoformat(),
                request.train_number or "",
            )
            _respect_provider_rate_limit(provider.source_id, environment)
            offers = provider.search_offers(request)
            if offers:
                logger.info("rail_provider_search_success source_id=%s offer_count=%s", provider.source_id, len(offers))
                return RailProviderSearchResult(offers=offers, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
            logger.info("rail_provider_search_empty source_id=%s", provider.source_id)
        except (httpx.HTTPError, RailProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
            logger.warning("rail_provider_search_failure source_id=%s error=%s", provider.source_id, exc)
    if not attempted_source_ids:
        logger.warning("rail_provider_search_no_enabled_provider source_id=rail_12306_public_query")
    return RailProviderSearchResult(offers=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def station_code_for_name(station_name: str) -> str | None:
    return _station_codes_by_normalized_name().get(_normalize_station_name(station_name))


@lru_cache(maxsize=1)
def _station_codes_by_normalized_name() -> dict[str, str]:
    payload = json.loads(TRANSPORT_NODES_PATH.read_text(encoding="utf-8"))
    stations = payload.get("stations") or []
    code_by_name: dict[str, str] = {}
    for station in stations:
        station_code = station.get("station_code")
        if not station_code:
            continue
        names = [station.get("node_name"), *(station.get("aliases") or [])]
        for name in names:
            text = str(name or "").strip()
            if not text:
                continue
            _remember_station_code(code_by_name, text, station_code)
            if text.endswith("站"):
                _remember_station_code(code_by_name, text[:-1], station_code)
            else:
                _remember_station_code(code_by_name, f"{text}站", station_code)
    return code_by_name


def _remember_station_code(code_by_name: dict[str, str], name: str, station_code: str) -> None:
    normalized = _normalize_station_name(name)
    if normalized and normalized not in code_by_name:
        code_by_name[normalized] = station_code


def _normalize_station_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _seat_options_from_12306_row(parts: list[str], prices: dict[str, Money], train_number: str, data_source: DataSourceMetadata) -> list[SeatOption]:
    seats: list[SeatOption] = []
    for seat_code, seat_name, availability_index in _seat_definitions():
        if availability_index >= len(parts):
            continue
        availability = _availability_from_12306(parts[availability_index])
        price = prices.get(seat_code)
        if availability not in {"AVAILABLE", "LIMITED"} or price is None:
            continue
        option_id = f"seat_{seat_code.lower()}_{len(seats) + 1}"
        seats.append(
            SeatOption(
                option_id=option_id,
                seat_type=seat_name,
                price=price,
                availability=availability,
                source_option_version=f"12306_{train_number}_{seat_code}",
                data_source=data_source,
            )
        )
    return seats


def _seat_definitions() -> list[tuple[str, str, int]]:
    return [
        ("9", "商务座", 32),
        ("P", "特等座", 32),
        ("M", "一等座", 31),
        ("O", "二等座", 30),
        ("6", "高级软卧", 21),
        ("4", "软卧", 23),
        ("3", "硬卧", 28),
        ("2", "软座", 24),
        ("1", "硬座", 29),
        ("W", "无座", 26),
        ("A", "高级动卧", 33),
        ("F", "动卧", 33),
    ]


def _parse_12306_price_blob(value: str) -> dict[str, Money]:
    prices: dict[str, Money] = {}
    for seat_code, price_text in re.findall(r"([A-Z0-9])(\d{5})", value or ""):
        if seat_code in prices:
            continue
        price_units = int(price_text)
        if price_units <= 0:
            continue
        prices[seat_code] = money(price_units * 10)
    return prices


def _train_number_from_12306_row(raw_item: str) -> str | None:
    parts = raw_item.split("|")
    if len(parts) <= 3:
        return None
    return parts[3].strip() or None


def _availability_from_12306(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"--", "候补"}:
        return "NO_TICKET"
    if text in {"无", "0"}:
        return "NO_TICKET"
    if text == "少":
        return "LIMITED"
    if text == "有":
        return "AVAILABLE"
    if text.isdigit():
        return "AVAILABLE" if int(text) > 0 else "NO_TICKET"
    return "NO_TICKET"


def _parse_train_time(departure_date: date, value: Any) -> datetime:
    if value is None or value == "":
        raise RailProviderError("12306 rail offer time is missing")
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) == 2:
        text = f"{text}:00"
    return datetime.fromisoformat(f"{departure_date.isoformat()}T{text}").replace(tzinfo=SHANGHAI_TZ)


def _duration_minutes(value: Any, departure_at: datetime, arrival_at: datetime) -> int:
    if value is None or value == "":
        return max(0, int((arrival_at - departure_at).total_seconds() // 60))
    text = str(value).strip()
    if ":" in text:
        hours_text, minutes_text = text.split(":", 1)
        return int(hours_text) * 60 + int(minutes_text)
    match = re.search(r"(?:(\d+)\s*天)?\s*(?:(\d+)\s*(?:小时|时|h))?\s*(?:(\d+)\s*(?:分钟|分|m))?", text)
    if match and any(match.groups()):
        days = int(match.group(1) or 0)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)
        return days * 24 * 60 + hours * 60 + minutes
    return max(0, int((arrival_at - departure_at).total_seconds() // 60))


def _respect_provider_rate_limit(source_id: str, environment: str | None) -> None:
    interval_seconds = _provider_min_interval_seconds(source_id, environment)
    if interval_seconds <= 0:
        return
    with _RATE_LIMIT_LOCK:
        now = _monotonic()
        previous = _LAST_PROVIDER_CALL_AT.get(source_id)
        if previous is not None:
            wait_seconds = interval_seconds - (now - previous)
            if wait_seconds > 0:
                logger.info("rail_provider_rate_limit_wait source_id=%s wait_seconds=%.3f", source_id, wait_seconds)
                _sleep(wait_seconds)
                now = _monotonic()
        _LAST_PROVIDER_CALL_AT[source_id] = now


def _provider_min_interval_seconds(source_id: str, environment: str | None) -> float:
    env_override = os.getenv(f"TRAVEL_SOURCE_{source_id.upper()}_MIN_INTERVAL_SECONDS")
    if env_override:
        return _safe_float(env_override, 1.0)
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get(source_id)
    if config and config.qps_limit > 0:
        return 1.0 / config.qps_limit
    return 1.0 if source_id == "rail_12306_public_query" else 0.0


def _public_query_cache_ttl_seconds() -> int:
    return int(os.getenv("TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_CACHE_TTL_SECONDS", "60"))


def _safe_float(value: str, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except ValueError:
        return fallback


def _cache_get(key: str, ttl_seconds: int) -> list[RailOffer] | None:
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


def _cache_set(key: str, offers: list[RailOffer], ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    _SEARCH_CACHE[key] = (_monotonic() + ttl_seconds, offers)


def _offer_with_cache_metadata(offer: RailOffer, *, cache_hit: bool, ttl_seconds: int | None) -> RailOffer:
    data_source = rail_data_source_metadata(offer.data_source.source_id, offer.data_source.source_name, cache_hit=cache_hit, cache_ttl_seconds=ttl_seconds)
    seats = [seat.model_copy(update={"data_source": data_source}) for seat in offer.seat_options]
    return RailOffer(
        train_number=offer.train_number,
        origin_station=offer.origin_station,
        destination_station=offer.destination_station,
        departure_at=offer.departure_at,
        arrival_at=offer.arrival_at,
        duration_minutes=offer.duration_minutes,
        stop_sequence=offer.stop_sequence,
        seat_options=seats,
        data_source=data_source,
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
