from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, overload
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.data_sources.flight_providers import (
    FlightOffer,
    FlightOfferCabinOption,
    FlightOfferSegment,
    FlightSearchRequest,
)
from app.data_sources.flyai_cli_client import FlyAIClient, FlyAIClientError, FlyAICommandResult
from app.data_sources.provider_booking import ProviderBookingReference
from app.data_sources.rail_providers import RailOffer, RailSearchRequest
from app.data_sources.runtime_health import RuntimeHealthRegistry, runtime_health_registry
from app.models.schemas import CacheMetadata, DataSourceMetadata, DataSourceType, Money, SeatOption, TimePoint

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_FLIGHT_NUMBER_RE = re.compile(r"^([A-Z0-9]{2})([A-Z0-9]{2,6})$")
_TRAIN_NUMBER_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")
_EXACT_PRICE_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")


class FliggyFlyAIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class _CachedCommand:
    result: FlyAICommandResult
    fetched_at: datetime
    cache_hit: bool = False


_CACHE_LOCK = threading.Lock()
_COMMAND_CACHE: dict[str, tuple[float, _CachedCommand]] = {}
_IN_FLIGHT: dict[str, Future[_CachedCommand]] = {}
_RATE_LOCK = threading.Lock()
_LAST_CALL_AT: dict[str, float] = {}


class FliggyFlyAIProvider:
    source_id = "fliggy_flyai"
    query_scope = "CITY"
    uses_city_names = True

    def __init__(
        self,
        *,
        client: FlyAIClient,
        qps_limit: int,
        cache_ttl_seconds: int,
        redirect_allowed_hosts: tuple[str, ...],
        runtime_registry: RuntimeHealthRegistry = runtime_health_registry,
    ) -> None:
        if qps_limit <= 0:
            raise FliggyFlyAIProviderError("FLIGGY_CONFIGURATION_ERROR: QPS limit must be positive")
        if not redirect_allowed_hosts:
            raise FliggyFlyAIProviderError("FLIGGY_CONFIGURATION_ERROR: redirect host allowlist is empty")
        self.client = client
        self.qps_limit = qps_limit
        self.cache_ttl_seconds = cache_ttl_seconds
        self.redirect_allowed_hosts = tuple(host.lower().strip(".") for host in redirect_allowed_hosts)
        self._runtime_registry = runtime_registry

    @overload
    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]: ...

    @overload
    def search_offers(self, request: RailSearchRequest) -> list[RailOffer]: ...

    def search_offers(self, request: FlightSearchRequest | RailSearchRequest) -> list[FlightOffer] | list[RailOffer]:
        if isinstance(request, FlightSearchRequest):
            return self._search_flights(request)
        if isinstance(request, RailSearchRequest):
            return self._search_trains(request)
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_INPUT: unsupported search request")

    def _search_flights(self, request: FlightSearchRequest) -> list[FlightOffer]:
        origin = (request.origin_city_name or "").strip()
        destination = (request.destination_city_name or "").strip()
        if not origin or not destination:
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_INPUT: Chinese city names are required")
        cache_key = _query_key(
            "flight",
            origin,
            destination,
            request.departure_date.isoformat(),
            str(request.non_stop),
            request.currency_code,
        )
        cached = self._execute_cached(
            cache_key,
            lambda: self.client.search_flight(
                origin=origin,
                destination=destination,
                departure_date=request.departure_date,
                non_stop=request.non_stop,
                sort_type=3,
            ),
        )
        items = _items(cached.result.payload)
        offers: list[FlightOffer] = []
        rejected_price = 0
        for item in items:
            try:
                offers.append(self._flight_offer(item, cached))
            except FliggyFlyAIProviderError as exc:
                if "FLIGGY_PRICE_NOT_EXACT" in str(exc):
                    rejected_price += 1
                continue
        if items and not offers:
            code = "FLIGGY_PRICE_NOT_EXACT" if rejected_price == len(items) else "FLIGGY_INVALID_RESPONSE"
            self._record_invalid_provider_response(cached, code)
            raise FliggyFlyAIProviderError(f"{code}: all FlyAI flight items were rejected")
        return sorted(
            offers,
            key=lambda offer: (offer.total_price.amount_minor, offer.segments[0].departure_at or datetime.max.replace(tzinfo=SHANGHAI_TZ)),
        )[: max(1, request.max_results)]

    def _search_trains(self, request: RailSearchRequest) -> list[RailOffer]:
        cache_key = _query_key(
            "train",
            request.origin_station,
            request.destination_station,
            request.departure_date.isoformat(),
            request.train_number,
        )
        cached = self._execute_cached(
            cache_key,
            lambda: self.client.search_train(
                origin=request.origin_station,
                destination=request.destination_station,
                departure_date=request.departure_date,
                train_number=request.train_number or None,
                sort_type=3,
            ),
        )
        items = _items(cached.result.payload)
        offers: list[RailOffer] = []
        rejected_price = 0
        for item in items:
            try:
                offer = self._rail_offer(item, cached)
            except FliggyFlyAIProviderError as exc:
                if "FLIGGY_PRICE_NOT_EXACT" in str(exc):
                    rejected_price += 1
                continue
            if request.train_number and offer.train_number.upper() != request.train_number.strip().upper():
                continue
            offers.append(offer)
        if items and not offers:
            code = "FLIGGY_PRICE_NOT_EXACT" if rejected_price == len(items) else "FLIGGY_INVALID_RESPONSE"
            self._record_invalid_provider_response(cached, code)
            raise FliggyFlyAIProviderError(f"{code}: all FlyAI rail items were rejected")
        return sorted(offers, key=lambda offer: offer.departure_at)

    def _execute_cached(self, cache_key: str, command: Callable[[], FlyAICommandResult]) -> _CachedCommand:
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _COMMAND_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return _CachedCommand(cached[1].result, cached[1].fetched_at, cache_hit=True)
            if cached:
                _COMMAND_CACHE.pop(cache_key, None)
            future = _IN_FLIGHT.get(cache_key)
            leader = future is None
            if leader:
                future = Future()
                _IN_FLIGHT[cache_key] = future
        assert future is not None
        if not leader:
            return future.result(timeout=self.client.timeout_seconds + 2)
        try:
            self._respect_rate_limit()
            completed = _CachedCommand(command(), datetime.now(tz=SHANGHAI_TZ))
            with _CACHE_LOCK:
                if self.cache_ttl_seconds > 0:
                    _COMMAND_CACHE[cache_key] = (time.monotonic() + self.cache_ttl_seconds, completed)
            future.set_result(completed)
            return completed
        except FlyAIClientError as exc:
            wrapped = FliggyFlyAIProviderError(str(exc))
            future.set_exception(wrapped)
            raise wrapped from exc
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with _CACHE_LOCK:
                _IN_FLIGHT.pop(cache_key, None)

    def _respect_rate_limit(self) -> None:
        interval = 1.0 / self.qps_limit
        with _RATE_LOCK:
            now = time.monotonic()
            previous = _LAST_CALL_AT.get(self.source_id)
            if previous is not None and now - previous < interval:
                time.sleep(interval - (now - previous))
            _LAST_CALL_AT[self.source_id] = time.monotonic()

    def _record_invalid_provider_response(self, cached: _CachedCommand, error_code: str) -> None:
        self._runtime_registry.record_failure(
            self.source_id,
            failure_kind="INVALID_RESPONSE",
            error_code=error_code,
            retryable=error_code != "FLIGGY_PRICE_NOT_EXACT",
            latency_ms=cached.result.elapsed_ms,
        )

    def _flight_offer(self, item: Any, cached: _CachedCommand) -> FlightOffer:
        item_dict = _item_dict(item)
        price = _exact_money(item_dict.get("ticketPrice", item_dict.get("adultPrice")), "flight")
        reference = self._booking_reference(item_dict, cached.fetched_at)
        raw_segments = _journey_segments(item_dict)
        segments: list[FlightOfferSegment] = []
        cabin_types: list[str] = []
        previous_arrival: datetime | None = None
        for raw in raw_segments:
            if raw.get("depCityAbroad") is True or raw.get("arrCityAbroad") is True:
                raise FliggyFlyAIProviderError("FLIGGY_UNSUPPORTED_ROUTE: international timezone is unsupported")
            flight_number = str(raw.get("marketingTransportNo") or "").strip().upper()
            match = _FLIGHT_NUMBER_RE.fullmatch(flight_number)
            origin_iata = str(raw.get("depStationCode") or "").strip().upper()
            destination_iata = str(raw.get("arrStationCode") or "").strip().upper()
            departure_at = _parse_datetime(raw.get("depDateTime"))
            arrival_at = _parse_datetime(raw.get("arrDateTime"))
            if not match or not _AIRPORT_RE.fullmatch(origin_iata) or not _AIRPORT_RE.fullmatch(destination_iata):
                raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: flight identity is invalid")
            if arrival_at <= departure_at or (previous_arrival and departure_at < previous_arrival):
                raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: flight chronology is invalid")
            if segments and segments[-1].destination_iata != origin_iata:
                raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: connecting airports do not match")
            cabin_type = str(raw.get("seatClassName") or "").strip()
            if not cabin_type:
                raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: cabin is missing")
            cabin_types.append(cabin_type)
            segments.append(
                FlightOfferSegment(
                    carrier_code=match.group(1),
                    flight_number=match.group(2),
                    origin_iata=origin_iata,
                    destination_iata=destination_iata,
                    departure_at=departure_at,
                    arrival_at=arrival_at,
                    duration=str(raw.get("duration") or "") or None,
                )
            )
            previous_arrival = arrival_at
        cabins = [
            FlightOfferCabinOption(
                option_id=f"flyai_cabin_{index}",
                cabin_type=cabin,
                price=price,
                availability="AVAILABLE",
                source_option_version=reference.item_fingerprint,
                inventory_evidence="FLIGGY_ITEM_RETURNED",
            )
            for index, cabin in enumerate(dict.fromkeys(cabin_types), start=1)
        ]
        metadata = self._metadata(cached)
        offer_id = f"flyai_flight_{reference.item_fingerprint[:16]}"
        return FlightOffer(
            offer_id=offer_id,
            source=self.source_id,
            total_price=price,
            currency="CNY",
            segments=segments,
            validating_airline_codes=list(dict.fromkeys(segment.carrier_code for segment in segments)),
            raw_offer={"item_fingerprint": reference.item_fingerprint, "response_hash": cached.result.response_hash},
            data_source=metadata,
            cabin_options=cabins,
            evidence_id=f"flyai_{cached.result.response_hash[:16]}",
            booking_reference=reference,
        )

    def _rail_offer(self, item: Any, cached: _CachedCommand) -> RailOffer:
        item_dict = _item_dict(item)
        price = _exact_money(item_dict.get("price"), "rail")
        reference = self._booking_reference(item_dict, cached.fetched_at)
        raw_segments = _journey_segments(item_dict)
        if len(raw_segments) != 1:
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: rail item is not one direct segment")
        raw = raw_segments[0]
        train_number = str(raw.get("marketingTransportNo") or "").strip().upper()
        if not _TRAIN_NUMBER_RE.fullmatch(train_number):
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: train number is invalid")
        departure_at = _parse_datetime(raw.get("depDateTime"))
        arrival_at = _parse_datetime(raw.get("arrDateTime"))
        if arrival_at <= departure_at:
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: rail chronology is invalid")
        origin_station = str(raw.get("depStationName") or "").strip()
        destination_station = str(raw.get("arrStationName") or "").strip()
        seat_type = str(raw.get("seatClassName") or "").strip()
        if not origin_station or not destination_station or not seat_type:
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: rail station or seat is missing")
        metadata = self._metadata(cached)
        seat = SeatOption(
            option_id=f"flyai_seat_{reference.item_fingerprint[:12]}",
            seat_type=seat_type,
            price=price,
            availability="AVAILABLE",
            source_option_version=reference.item_fingerprint,
            data_source=metadata,
        )
        return RailOffer(
            train_number=train_number,
            origin_station=origin_station,
            destination_station=destination_station,
            departure_at=departure_at,
            arrival_at=arrival_at,
            duration_minutes=max(1, int((arrival_at - departure_at).total_seconds() // 60)),
            stop_sequence=[origin_station, destination_station],
            seat_options=[seat],
            data_source=metadata,
            origin_station_code=str(raw.get("depStationCode") or "").strip().upper() or None,
            destination_station_code=str(raw.get("arrStationCode") or "").strip().upper() or None,
            booking_reference=reference,
        )

    def _booking_reference(self, item: dict[str, Any], fetched_at: datetime) -> ProviderBookingReference:
        url = str(item.get("jumpUrl") or "").strip()
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().strip(".")
        if parsed.scheme != "https" or not hostname or not _host_allowed(hostname, self.redirect_allowed_hosts):
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: jump URL is not allowlisted HTTPS")
        fingerprint_payload = {
            "journeys": item.get("journeys"),
            "ticketPrice": item.get("ticketPrice"),
            "adultPrice": item.get("adultPrice"),
            "price": item.get("price"),
            "jumpUrl": url,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ProviderBookingReference(
            source_id=self.source_id,
            redirect_url=url,
            item_fingerprint=fingerprint,
            fetched_at=fetched_at,
        )

    def _metadata(self, cached: _CachedCommand) -> DataSourceMetadata:
        return DataSourceMetadata(
            source_id=self.source_id,
            source_name="Fliggy FlyAI",
            source_type=DataSourceType.OTA,
            authority_level="A",
            source_priority=10,
            source_region="CN",
            api_version="flyai-cli-1.0.16",
            license_status="APPROVED",
            commercial_allowed=False,
            fetched_at=TimePoint(datetime=cached.fetched_at, timezone="Asia/Shanghai", source_timezone="Asia/Shanghai"),
            cacheable=True,
            cache_ttl_seconds=self.cache_ttl_seconds,
            sla_level="OFFICIAL_CLI",
            cache_metadata=CacheMetadata(
                cacheable=True,
                cache_ttl_seconds=self.cache_ttl_seconds,
                cache_hit=cached.cache_hit,
            ),
        )


def _items(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    items = data.get("itemList") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: itemList is missing")
    return items


def _item_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: item is not an object")
    return value


def _journey_segments(item: dict[str, Any]) -> list[dict[str, Any]]:
    journeys = item.get("journeys")
    if not isinstance(journeys, list) or not journeys:
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: journeys are missing")
    segments: list[dict[str, Any]] = []
    for journey in journeys:
        if not isinstance(journey, dict) or not isinstance(journey.get("segments"), list):
            raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: journey segments are invalid")
        for segment in journey["segments"]:
            if not isinstance(segment, dict):
                raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: segment is invalid")
            segments.append(segment)
    if not segments:
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: no segments returned")
    return segments


def _exact_money(value: Any, product: str) -> Money:
    text = str(value or "").strip()
    if not _EXACT_PRICE_RE.fullmatch(text):
        raise FliggyFlyAIProviderError(f"FLIGGY_PRICE_NOT_EXACT: {product} price is not exact")
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise FliggyFlyAIProviderError(f"FLIGGY_PRICE_NOT_EXACT: {product} price is invalid") from exc
    amount_minor = int((decimal_value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount_minor <= 0:
        raise FliggyFlyAIProviderError(f"FLIGGY_PRICE_NOT_EXACT: {product} price is invalid")
    return Money(
        amount_minor=amount_minor,
        currency="CNY",
        scale=2,
        is_estimated=False,
        display_text=f"¥{decimal_value.quantize(Decimal('0.01'))}",
    )


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: datetime is missing")
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError as exc:
        raise FliggyFlyAIProviderError("FLIGGY_INVALID_RESPONSE: datetime is invalid") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _host_allowed(hostname: str, allowed_hosts: tuple[str, ...]) -> bool:
    return any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in allowed_hosts)


def _query_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
