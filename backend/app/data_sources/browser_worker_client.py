from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserWorkerClientError(RuntimeError):
    pass


class _HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _HttpClient(Protocol):
    def post(self, url: str, *, json: dict[str, object]) -> _HttpResponse: ...


class BrowserWorkerMoney(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    scale: int = Field(ge=0, le=6)


class BrowserWorkerFare(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fare_id: str = Field(min_length=1, max_length=160)
    cabin_type: Literal["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"]
    price: BrowserWorkerMoney
    availability: Literal["AVAILABLE", "LIMITED"]
    remaining_count: int | None = Field(default=None, gt=0)


class BrowserWorkerFlight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    flight_id: str = Field(min_length=1, max_length=160)
    carrier_code: Literal["MU", "FM"]
    flight_number: str = Field(pattern=r"^\d{3,4}[A-Z]?$")
    origin_iata: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata: str = Field(pattern=r"^[A-Z]{3}$")
    departure_at: datetime
    arrival_at: datetime
    fares: tuple[BrowserWorkerFare, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_times(self) -> "BrowserWorkerFlight":
        if self.departure_at.tzinfo is None or self.arrival_at.tzinfo is None:
            raise ValueError("flight times must include timezone")
        if self.arrival_at <= self.departure_at:
            raise ValueError("arrival_at must be after departure_at")
        return self


class BrowserWorkerSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    source_id: str
    flights: tuple[BrowserWorkerFlight, ...] = ()
    evidence_id: str | None = Field(default=None, max_length=160)
    cache_hit: bool = False
    error_code: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=500)
    retryable: bool | None = None
    challenge: dict[str, str] | None = None
    queue_ms: int = Field(ge=0)
    navigation_ms: int = Field(ge=0)
    response_ms: int = Field(ge=0)
    parse_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_result_shape(self) -> "BrowserWorkerSearchResponse":
        if self.success:
            if not self.evidence_id or self.error_code or self.message or self.retryable is not None or self.challenge:
                raise ValueError("successful worker response has an invalid shape")
        elif self.flights or not self.error_code or not self.message or self.retryable is None or self.evidence_id:
            raise ValueError("failed worker response has an invalid shape")
        return self


class BrowserWorkerClient:
    def __init__(
        self,
        *,
        worker_url: str,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: float,
        client: _HttpClient | None = None,
    ) -> None:
        self.worker_url = _validated_worker_url(worker_url, allowed_hosts)
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(2.0, timeout_seconds)),
            follow_redirects=False,
        )

    def search(
        self,
        *,
        request_id: str,
        source_id: str,
        origin_iata: str,
        destination_iata: str,
        departure_date: str,
        adults: int,
        currency_code: str,
        max_results: int,
    ) -> BrowserWorkerSearchResponse:
        try:
            response = self.client.post(
                f"{self.worker_url}/v1/flight-search",
                json={
                    "request_id": request_id,
                    "source_id": source_id,
                    "origin_iata": origin_iata,
                    "destination_iata": destination_iata,
                    "departure_date": departure_date,
                    "adults": adults,
                    "currency_code": currency_code,
                    "max_results": max_results,
                },
            )
            response.raise_for_status()
            payload = BrowserWorkerSearchResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise BrowserWorkerClientError("browser worker unavailable or returned an invalid response") from exc
        if payload.source_id != source_id:
            raise BrowserWorkerClientError("browser worker source_id mismatch")
        return payload


def _validated_worker_url(worker_url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(worker_url)
    hostname = (parsed.hostname or "").lower().strip(".")
    normalized_allowlist = {item.lower().strip(".") for item in allowed_hosts}
    if parsed.scheme != "http" or not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BrowserWorkerClientError("browser worker URL must be a plain internal HTTP origin")
    if hostname not in {"127.0.0.1", "localhost", "::1"} or hostname not in normalized_allowlist:
        raise BrowserWorkerClientError("browser worker URL is outside the loopback allowlist")
    base_path = parsed.path.rstrip("/")
    if base_path:
        raise BrowserWorkerClientError("browser worker URL must not include a path")
    return worker_url.rstrip("/")
