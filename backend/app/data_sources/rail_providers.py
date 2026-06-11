from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, Money, SeatOption, money, now_timepoint


class RailProviderError(RuntimeError):
    pass


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
        response = self.client.get(
            f"{self.base_url}/rail/offers",
            headers={"Authorization": f"Bearer {self.api_key}"},
            params={
                "train_number": request.train_number,
                "origin_station": request.origin_station,
                "destination_station": request.destination_station,
                "departure_date": request.departure_date.isoformat(),
            },
        )
        response.raise_for_status()
        payload = response.json()
        return [self._parse_offer(item) for item in payload.get("data", [])]

    def _parse_offer(self, item: dict[str, Any]) -> RailOffer:
        train_number = str(item.get("train_number") or "")
        origin_station = str(item.get("origin_station") or "")
        destination_station = str(item.get("destination_station") or "")
        departure_at = _parse_datetime(item.get("departure_at"))
        arrival_at = _parse_datetime(item.get("arrival_at"))
        duration_minutes = int((arrival_at - departure_at).total_seconds() // 60)
        data_source = rail_data_source_metadata("rail_authorized_partner", "Authorized Rail Partner API")
        seats = [
            SeatOption(
                option_id=str(seat.get("option_id") or f"seat_{index}"),
                seat_type=str(seat.get("seat_type") or ""),
                price=_price_to_money(seat.get("price") or seat.get("price_minor") or 0),
                availability=str(seat.get("availability") or "UNKNOWN"),
                source_option_version=str(seat.get("source_option_version") or "rail_partner"),
                data_source=data_source,
            )
            for index, seat in enumerate(item.get("seat_options") or [])
        ]
        if not seats:
            raise RailProviderError("rail offer has no seat_options")
        return RailOffer(
            train_number=train_number,
            origin_station=origin_station,
            destination_station=destination_station,
            departure_at=departure_at,
            arrival_at=arrival_at,
            duration_minutes=duration_minutes,
            stop_sequence=list(item.get("stop_sequence") or [origin_station, destination_station]),
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
        update_frequency="REALTIME_API",
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


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise RailProviderError("rail offer datetime is missing")
    return datetime.fromisoformat(value)


def _price_to_money(value: Any) -> Money:
    if isinstance(value, int):
        return money(value)
    amount_minor = int(round(float(value) * 100))
    return money(amount_minor)


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
