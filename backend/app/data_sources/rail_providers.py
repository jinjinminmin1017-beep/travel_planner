from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, Money, SeatOption, money, now_timepoint


class RailProviderError(RuntimeError):
    pass


_RATE_LIMIT_LOCK = threading.Lock()
_LAST_PROVIDER_CALL_AT: dict[str, float] = {}
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


@dataclass(frozen=True)
class RailConnectionRequest:
    origin_station: str
    destination_station: str
    departure_date: date | None = None
    departure_time: str | None = None
    timesel: str = "departure"
    results: int = 3
    lang: str = "en"


@dataclass(frozen=True)
class RailConnection:
    connection_id: str
    train_number: str
    origin_station: str
    destination_station: str
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int
    transfer_count: int
    platforms: list[str]
    vehicles: list[str]
    occupancy: str | None
    canceled: bool
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class RailConnectionSearchResult:
    connections: list[RailConnection]
    attempted_source_ids: list[str]
    failure_message: str | None = None


class RailProvider(Protocol):
    source_id: str

    def search_offers(self, request: RailSearchRequest) -> list[RailOffer]:
        ...


class RailConnectionProvider(Protocol):
    source_id: str

    def search_connections(self, request: RailConnectionRequest) -> list[RailConnection]:
        ...


class AuthorizedRailPartnerProvider:
    source_id = "rail_authorized_partner"

    def __init__(self, api_key: str, base_url: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)

    def search_offers(self, request: RailSearchRequest) -> list[RailOffer]:
        train_filter = _juhe_train_filter(request.train_number)
        response = self.client.get(
            self.base_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            params={
                "key": self.api_key,
                "search_type": "1",
                "departure_station": request.origin_station,
                "arrival_station": request.destination_station,
                "date": request.departure_date.isoformat(),
                "filter": train_filter,
                "enable_booking": "2",
                "departure_time_range": "",
            },
        )
        response.raise_for_status()
        payload = response.json()
        error_code = int(payload.get("error_code") or 0)
        if error_code != 0:
            raise RailProviderError(f"juhe rail query failed: {payload.get('reason') or error_code}")
        items = payload.get("result") or []
        if not isinstance(items, list):
            raise RailProviderError("juhe rail response has invalid result payload")
        offers = [self._parse_offer(item, request.departure_date) for item in items]
        if request.train_number:
            requested_train = request.train_number.strip().upper()
            offers = [offer for offer in offers if offer.train_number.upper() == requested_train]
        return sorted(offers, key=lambda offer: 0 if offer.train_number == request.train_number else 1)

    def _parse_offer(self, item: dict[str, Any], departure_date: date) -> RailOffer:
        train_number = str(item.get("train_no") or "")
        origin_station = str(item.get("departure_station") or "")
        destination_station = str(item.get("arrival_station") or "")
        departure_at = _parse_train_time(departure_date, item.get("departure_time"))
        arrival_at = _parse_train_time(departure_date, item.get("arrival_time"))
        if arrival_at < departure_at:
            arrival_at = arrival_at + timedelta(days=1)
        duration_minutes = _duration_minutes(item.get("duration"), departure_at, arrival_at)
        data_source = rail_data_source_metadata("rail_authorized_partner", "Juhe Train Query API")
        seats = [
            SeatOption(
                option_id=f"seat_{seat.get('seat_type_code') or index}",
                seat_type=str(seat.get("seat_name") or ""),
                price=_price_to_money(seat.get("price") or 0),
                availability=_juhe_availability(seat.get("num")),
                source_option_version=f"juhe_{train_number}_{seat.get('seat_type_code') or index}",
                data_source=data_source,
            )
            for index, seat in enumerate(item.get("prices") or [])
            if seat.get("seat_name") and seat.get("price") is not None
        ]
        if not seats:
            raise RailProviderError("juhe rail offer has no prices")
        return RailOffer(
            train_number=train_number,
            origin_station=origin_station,
            destination_station=destination_station,
            departure_at=departure_at,
            arrival_at=arrival_at,
            duration_minutes=duration_minutes,
            stop_sequence=[origin_station, destination_station],
            seat_options=seats,
            data_source=data_source,
        )


class IRailConnectionsProvider:
    source_id = "irail_connections"

    def __init__(self, client: httpx.Client | None = None, base_url: str | None = None, user_agent: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("IRAIL_BASE_URL") or "https://api.irail.be").rstrip("/")
        self.client = client or httpx.Client(timeout=10.0, follow_redirects=True)
        self.user_agent = user_agent or os.getenv("IRAIL_USER_AGENT") or "AITravelPlanner/0.1 (local-dev)"

    def search_connections(self, request: RailConnectionRequest) -> list[RailConnection]:
        params: dict[str, str | int] = {
            "from": request.origin_station,
            "to": request.destination_station,
            "timesel": request.timesel,
            "format": "json",
            "lang": request.lang,
            "typeOfTransport": "automatic",
            "alerts": "false",
            "results": max(1, min(request.results, 6)),
        }
        if request.departure_date:
            params["date"] = request.departure_date.strftime("%d%m%y")
        if request.departure_time:
            params["time"] = request.departure_time

        response = self.client.get(
            f"{self.base_url}/connections/",
            params=params,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        connections = payload.get("connection") or []
        if not isinstance(connections, list):
            raise RailProviderError("iRail response has invalid connection payload")
        return [self._parse_connection(item) for item in connections]

    def _parse_connection(self, item: dict[str, Any]) -> RailConnection:
        departure = item.get("departure") or {}
        arrival = item.get("arrival") or {}
        departure_at = _parse_epoch(departure.get("time"))
        arrival_at = _parse_epoch(arrival.get("time"))
        duration_seconds = _safe_int(item.get("duration"))
        duration_minutes = max(0, duration_seconds // 60) if duration_seconds else int((arrival_at - departure_at).total_seconds() // 60)
        vias = item.get("vias") or {}
        transfer_count = _safe_int(vias.get("number")) if isinstance(vias, dict) else 0
        platforms = _non_empty_strings([departure.get("platform"), arrival.get("platform")])
        vehicles = _non_empty_strings([
            _vehicle_name(departure),
            _vehicle_name(arrival),
            *_via_vehicle_names(vias),
        ])
        occupancy = (item.get("occupancy") or departure.get("occupancy") or {}).get("name")
        return RailConnection(
            connection_id=str(item.get("id") or ""),
            train_number=_vehicle_name(departure) or _vehicle_name(arrival) or "",
            origin_station=str(departure.get("station") or ""),
            destination_station=str(arrival.get("station") or ""),
            departure_at=departure_at,
            arrival_at=arrival_at,
            duration_minutes=duration_minutes,
            transfer_count=transfer_count,
            platforms=platforms,
            vehicles=vehicles,
            occupancy=str(occupancy) if occupancy is not None else None,
            canceled=_truthy(departure.get("canceled")) or _truthy(arrival.get("canceled")),
            data_source=rail_data_source_metadata(self.source_id, "iRail Connections API"),
        )


def rail_data_source_metadata(source_id: str, source_name: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.RAIL,
        authority_level="A",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
    )


def build_enabled_rail_providers(environment: str | None = None) -> list[RailProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("rail_authorized_partner")
    if not config or not config.enabled or config.license_status != "APPROVED" or not has_required_secret("rail_authorized_partner"):
        return []
    base_url = os.getenv("RAIL_PARTNER_BASE_URL")
    api_key = os.getenv("RAIL_PARTNER_API_KEY")
    if not base_url or not api_key:
        return []
    return [AuthorizedRailPartnerProvider(api_key=api_key, base_url=base_url)]


def build_enabled_rail_connection_providers(environment: str | None = None) -> list[RailConnectionProvider]:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("irail_connections")
    if config and config.enabled and config.license_status == "APPROVED":
        return [IRailConnectionsProvider()]
    return []


def search_rail_offers_with_enabled_provider_result(request: RailSearchRequest, environment: str | None = None) -> RailProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_rail_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            _respect_provider_rate_limit(provider.source_id, environment)
            offers = provider.search_offers(request)
            if offers:
                return RailProviderSearchResult(offers=offers, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
        except (httpx.HTTPError, RailProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
    return RailProviderSearchResult(offers=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def search_rail_connections_with_enabled_provider_result(request: RailConnectionRequest, environment: str | None = None) -> RailConnectionSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_rail_connection_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            connections = provider.search_connections(request)
            if connections:
                return RailConnectionSearchResult(connections=connections, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
        except (httpx.HTTPError, RailProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
    return RailConnectionSearchResult(connections=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def _price_to_money(value: Any) -> Money:
    amount_minor = int(round(float(value) * 100))
    return money(amount_minor)


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
                _sleep(wait_seconds)
                now = _monotonic()
        _LAST_PROVIDER_CALL_AT[source_id] = now


def _provider_min_interval_seconds(source_id: str, environment: str | None) -> float:
    env_override = os.getenv(f"TRAVEL_SOURCE_{source_id.upper()}_MIN_INTERVAL_SECONDS")
    if env_override:
        interval = _safe_float(env_override, 1.0)
        return max(interval, 1.25) if source_id == "rail_authorized_partner" else interval
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get(source_id)
    if config and config.qps_limit > 0:
        interval = 1.0 / config.qps_limit
        return max(interval, 1.25) if source_id == "rail_authorized_partner" else interval
    if source_id == "rail_authorized_partner":
        return 1.25
    return 0.0


def _safe_float(value: str, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except ValueError:
        return fallback


def _juhe_train_filter(train_number: str) -> str:
    prefix = (train_number or "").strip().upper()[:1]
    if prefix in {"G", "D", "Z", "T", "K"}:
        return prefix
    return ""


def _parse_train_time(departure_date: date, value: Any) -> datetime:
    if value is None or value == "":
        raise RailProviderError("juhe rail offer time is missing")
    text = str(value).strip()
    if "T" in text or re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text)
    parts = text.split(":")
    if len(parts) == 2:
        text = f"{text}:00"
    return datetime.fromisoformat(f"{departure_date.isoformat()}T{text}")


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


def _juhe_availability(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"--", "未知"}:
        return "UNKNOWN"
    if text in {"无", "0"}:
        return "NO_TICKET"
    if text == "少":
        return "LIMITED"
    if text == "有":
        return "AVAILABLE"
    if text.isdigit():
        return "AVAILABLE" if int(text) > 0 else "NO_TICKET"
    return text


def _parse_epoch(value: Any) -> datetime:
    if value is None or value == "":
        raise RailProviderError("iRail connection datetime is missing")
    return datetime.fromtimestamp(int(value))


def _safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _vehicle_name(point: dict[str, Any]) -> str:
    vehicle_info = point.get("vehicleinfo") or {}
    return str(vehicle_info.get("shortname") or vehicle_info.get("name") or point.get("vehicle") or "").strip()


def _via_vehicle_names(vias: Any) -> list[str]:
    if not isinstance(vias, dict):
        return []
    raw_vias = vias.get("via") or []
    if isinstance(raw_vias, dict):
        raw_vias = [raw_vias]
    names: list[str] = []
    for via in raw_vias:
        if isinstance(via, dict):
            names.extend([_vehicle_name(via.get("departure") or {}), _vehicle_name(via.get("arrival") or {})])
    return names


def _non_empty_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
