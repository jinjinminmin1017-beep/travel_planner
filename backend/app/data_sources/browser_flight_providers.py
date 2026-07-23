from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.data_sources.browser_worker_client import (
    BrowserWorkerClient,
    BrowserWorkerClientError,
    BrowserWorkerFlight,
)
from app.data_sources.flight_providers import (
    DEFAULT_FLIGHT_CACHE_TTL_SECONDS,
    DEFAULT_FLIGHT_SNAPSHOT_PATH,
    FlightOffer,
    FlightOfferCabinOption,
    FlightOfferSegment,
    FlightProviderError,
    FlightSearchRequest,
    _cache_get,
    _cache_key,
    _cache_set,
    _offer_with_cache_metadata,
    flight_data_source_metadata,
    save_flight_canonical_offers,
    save_flight_raw_snapshot,
)
from app.models.schemas import Money

logger = logging.getLogger("app.flight.browser")

MU_BROWSER_SOURCE_ID = "airline_mu_browser_query"


class BrowserAirlineFlightProvider:
    source_name = "China Eastern Official Browser Flight Query"
    query_scope: Literal["AIRPORT"] = "AIRPORT"

    def __init__(
        self,
        *,
        source_id: str,
        client: BrowserWorkerClient,
        cache_ttl_seconds: int = DEFAULT_FLIGHT_CACHE_TTL_SECONDS,
        snapshot_backend: Literal["sqlite", "disabled"] = "sqlite",
        snapshot_sqlite_path: str | Path = DEFAULT_FLIGHT_SNAPSHOT_PATH,
    ) -> None:
        if source_id != MU_BROWSER_SOURCE_ID:
            raise FlightProviderError(f"{source_id} browser handler is not implemented")
        if snapshot_backend not in {"sqlite", "disabled"}:
            raise FlightProviderError("browser flight snapshot backend is invalid")
        self.source_id = source_id
        self.client = client
        self.cache_ttl_seconds = cache_ttl_seconds
        self.snapshot_backend = snapshot_backend
        self.snapshot_sqlite_path = Path(snapshot_sqlite_path)

    def search_offers(self, request: FlightSearchRequest) -> list[FlightOffer]:
        request = request.for_query_scope(self.query_scope)
        if request.currency_code.upper() != "CNY":
            raise FlightProviderError(f"{self.source_id} currently supports CNY only")
        cache_key = _cache_key(self.source_id, request)
        cached = _cache_get(cache_key, self.cache_ttl_seconds)
        if cached is not None:
            return [
                _offer_with_cache_metadata(offer, cache_hit=True, ttl_seconds=self.cache_ttl_seconds)
                for offer in cached
            ]
        try:
            result = self.client.search(
                request_id=f"bw_{uuid4().hex[:16]}",
                source_id=self.source_id,
                origin_iata=request.origin_iata.upper(),
                destination_iata=request.destination_iata.upper(),
                departure_date=request.departure_date.isoformat(),
                adults=request.adults,
                currency_code=request.currency_code.upper(),
                max_results=request.max_results,
            )
        except BrowserWorkerClientError as exc:
            raise FlightProviderError(f"{self.source_id} worker unavailable or returned invalid data") from exc
        if not result.success:
            raise FlightProviderError(
                f"{self.source_id} {result.error_code}: {result.message}"
            )
        if not result.evidence_id:
            raise FlightProviderError(f"{self.source_id} response is missing evidence_id")
        snapshot_id = save_flight_raw_snapshot(
            source_id=self.source_id,
            request_key=cache_key,
            payload_text=json.dumps(result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")),
            content_type="application/json; browser-worker-canonical=1",
            snapshot_backend=self.snapshot_backend,
            snapshot_path=self.snapshot_sqlite_path,
        )
        offers = [
            self._offer_from_worker(flight, request, evidence_id=snapshot_id)
            for flight in result.flights
            if flight.origin_iata == request.origin_iata.upper()
            and flight.destination_iata == request.destination_iata.upper()
            and flight.departure_at.date() == request.departure_date
        ]
        if len(offers) != len(result.flights):
            raise FlightProviderError(f"{self.source_id} worker returned mismatched route or date")
        offers.sort(key=lambda item: item.segments[0].departure_at or result.flights[0].departure_at)
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
        logger.info(
            "browser_flight_search_result source_id=%s origin_iata=%s destination_iata=%s departure_date=%s "
            "offer_count=%s cache_hit=%s queue_ms=%s navigation_ms=%s response_ms=%s parse_ms=%s total_ms=%s",
            self.source_id,
            request.origin_iata.upper(),
            request.destination_iata.upper(),
            request.departure_date.isoformat(),
            len(offers),
            result.cache_hit,
            result.queue_ms,
            result.navigation_ms,
            result.response_ms,
            result.parse_ms,
            result.total_ms,
        )
        return offers

    def _offer_from_worker(
        self,
        flight: BrowserWorkerFlight,
        request: FlightSearchRequest,
        *,
        evidence_id: str,
    ) -> FlightOffer:
        cabins = [
            FlightOfferCabinOption(
                option_id=f"{self.source_id}_{fare.fare_id}",
                cabin_type=fare.cabin_type,
                price=_money(fare.price.amount_minor, fare.price.currency, fare.price.scale),
                availability=fare.availability,
                source_option_version=f"{self.source_id}_{result_token(evidence_id)}_{fare.fare_id}",
                inventory_evidence=(
                    f"browser_worker_remaining={fare.remaining_count}"
                    if fare.remaining_count is not None
                    else "browser_worker_public_availability"
                ),
                remaining_count=fare.remaining_count,
            )
            for fare in flight.fares
        ]
        selected = min(cabins, key=lambda item: item.price.amount_minor)
        data_source = flight_data_source_metadata(
            self.source_id,
            self.source_name,
            cache_hit=False,
            cache_ttl_seconds=self.cache_ttl_seconds,
            evidence_id=evidence_id,
        )
        return FlightOffer(
            offer_id=f"{self.source_id}_{flight.flight_id}",
            source="CHINA_EASTERN_BROWSER_WORKER",
            total_price=selected.price,
            currency=selected.price.currency,
            segments=[
                FlightOfferSegment(
                    carrier_code=flight.carrier_code,
                    flight_number=flight.flight_number,
                    origin_iata=flight.origin_iata,
                    destination_iata=flight.destination_iata,
                    departure_at=flight.departure_at,
                    arrival_at=flight.arrival_at,
                    duration=None,
                )
            ],
            validating_airline_codes=[flight.carrier_code],
            raw_offer={
                "flight_id": flight.flight_id,
                "flight_number": f"{flight.carrier_code}{flight.flight_number}",
                "origin_iata": flight.origin_iata,
                "destination_iata": flight.destination_iata,
                "departure_date": request.departure_date.isoformat(),
                "evidence_id": evidence_id,
            },
            data_source=data_source,
            cabin_options=cabins,
            evidence_id=evidence_id,
        )


def _money(amount_minor: int, currency: str, scale: int) -> Money:
    if currency != "CNY" or scale != 2:
        raise FlightProviderError("browser worker returned unsupported money currency or scale")
    return Money(
        amount_minor=amount_minor,
        currency=currency,
        scale=scale,
        is_estimated=False,
        display_text=f"¥{amount_minor // 100}.{amount_minor % 100:02d}",
    )


def result_token(evidence_id: str) -> str:
    return evidence_id[-16:]
