from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import DataSourceMetadata, DataSourceType, Money, money, now_timepoint


class FlightProviderError(RuntimeError):
    pass


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
class FlightOffer:
    offer_id: str
    source: str
    total_price: Money
    currency: str
    segments: list[FlightOfferSegment]
    validating_airline_codes: list[str]
    raw_offer: dict[str, Any]
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class FlightProviderSearchResult:
    offers: list[FlightOffer]
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

    def price_offer(self, offer: dict[str, Any]) -> FlightOffer:
        ...


class FlightStateProvider(Protocol):
    source_id: str

    def get_states(self, request: FlightStateRequest) -> list[FlightState]:
        ...


def flight_data_source_metadata(source_id: str, source_name: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.FLIGHT,
        authority_level="A",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        update_frequency="REALTIME_API",
        cacheable=True,
    )


class AmadeusFlightProvider:
    source_id = "amadeus_flight_offers"

    def __init__(self, client_id: str, client_secret: str, client: httpx.Client | None = None, base_url: str = "https://test.api.amadeus.com") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = client or httpx.Client(timeout=8.0)
        self.base_url = base_url.rstrip("/")
        self._access_token: str | None = None

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        response = self.client.get(
            f"{self.base_url}/v2/shopping/flight-offers",
            headers=self._headers(),
            params={
                "originLocationCode": request.origin_iata,
                "destinationLocationCode": request.destination_iata,
                "departureDate": request.departure_date.isoformat(),
                "adults": request.adults,
                "currencyCode": request.currency_code,
                "max": request.max_results,
                **({"nonStop": str(request.non_stop).lower()} if request.non_stop is not None else {}),
            },
        )
        response.raise_for_status()
        payload = response.json()
        return [self._parse_offer(item, "amadeus_flight_offers", "Amadeus Flight Offers Search API") for item in payload.get("data", [])]

    def price_offer(self, offer: dict[str, Any]) -> FlightOffer:
        response = self.client.post(
            f"{self.base_url}/v1/shopping/flight-offers/pricing",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"data": {"type": "flight-offers-pricing", "flightOffers": [offer]}},
        )
        response.raise_for_status()
        payload = response.json()
        offers = payload.get("data", {}).get("flightOffers") or []
        if not offers:
            raise FlightProviderError("Amadeus price response has no flightOffers")
        return self._parse_offer(offers[0], "amadeus_flight_price", "Amadeus Flight Offers Price API")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.client.post(
            f"{self.base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise FlightProviderError("Amadeus token response has no access_token")
        self._access_token = token
        return token

    def _parse_offer(self, offer: dict[str, Any], source_id: str, source_name: str) -> FlightOffer:
        price = offer.get("price") or {}
        total = price.get("grandTotal") or price.get("total")
        if total is None:
            raise FlightProviderError("Amadeus flight offer has no total price")
        currency = price.get("currency") or "CNY"
        segments: list[FlightOfferSegment] = []
        for itinerary in offer.get("itineraries", []):
            for segment in itinerary.get("segments", []):
                departure = segment.get("departure") or {}
                arrival = segment.get("arrival") or {}
                segments.append(
                    FlightOfferSegment(
                        carrier_code=segment.get("carrierCode", ""),
                        flight_number=segment.get("number", ""),
                        origin_iata=departure.get("iataCode", ""),
                        destination_iata=arrival.get("iataCode", ""),
                        departure_at=_parse_datetime(departure.get("at")),
                        arrival_at=_parse_datetime(arrival.get("at")),
                        duration=segment.get("duration"),
                    )
                )
        return FlightOffer(
            offer_id=str(offer.get("id") or ""),
            source=str(offer.get("source") or ""),
            total_price=_price_to_money(total, currency),
            currency=currency,
            segments=segments,
            validating_airline_codes=list(offer.get("validatingAirlineCodes") or []),
            raw_offer=offer,
            data_source=flight_data_source_metadata(source_id, source_name),
        )


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
    offers_config = configs.get("amadeus_flight_offers")
    if offers_config and offers_config.enabled and offers_config.license_status == "APPROVED" and _has_amadeus_credentials():
        providers.append(
            AmadeusFlightProvider(
                _first_env("AMADEUS_CLIENT_ID", "AMADEUS_API_KEY"),
                _first_env("AMADEUS_CLIENT_SECRET", "AMADEUS_API_SECRET"),
                base_url=os.getenv("AMADEUS_BASE_URL") or "https://test.api.amadeus.com",
            )
        )
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
    for provider in build_enabled_flight_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            offers = provider.search_offers(request)
            if offers:
                return FlightProviderSearchResult(offers=offers, attempted_source_ids=attempted_source_ids)
            failure_messages.append(f"{provider.source_id}: empty response")
        except (httpx.HTTPError, FlightProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
            continue
    return FlightProviderSearchResult(offers=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def get_flight_states_with_enabled_provider(request: FlightStateRequest, environment: str | None = None) -> list[FlightState]:
    for provider in build_enabled_flight_state_providers(environment):
        try:
            states = provider.get_states(request)
            if states:
                return states
        except (httpx.HTTPError, FlightProviderError, ValueError):
            continue
    return []


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise FlightProviderError(f"missing API credential env: {'/'.join(names)}")


def _has_amadeus_credentials() -> bool:
    return has_required_secret("amadeus_flight_offers") and any(os.getenv(name) for name in ("AMADEUS_CLIENT_SECRET", "AMADEUS_API_SECRET"))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _price_to_money(total: str, currency: str) -> Money:
    amount_minor = int(round(float(total) * 100))
    value = abs(amount_minor) / 100
    return Money(amount_minor=amount_minor, currency=currency, scale=2, is_estimated=False, display_text=f"{currency} {value:.2f}")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
