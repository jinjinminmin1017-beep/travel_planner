from __future__ import annotations

from datetime import date

import pytest

from app.data_sources.browser_flight_providers import BrowserAirlineFlightProvider
from app.data_sources.browser_worker_client import BrowserWorkerClient, BrowserWorkerClientError
from app.data_sources.flight_providers import FlightProviderError, FlightSearchRequest
from app.data_sources import flight_providers


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _FakeHttpClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[dict] = []

    def post(self, url: str, *, json: dict) -> _FakeResponse:
        self.requests.append({"url": url, "json": json})
        return _FakeResponse(self.payload)


@pytest.fixture(autouse=True)
def _clear_flight_cache() -> None:
    flight_providers._SEARCH_CACHE.clear()


def _success_payload() -> dict:
    return {
        "success": True,
        "source_id": "airline_mu_browser_query",
        "flights": [
            {
                "flight_id": "mu_6863_20260723",
                "carrier_code": "MU",
                "flight_number": "6863",
                "origin_iata": "PVG",
                "destination_iata": "TAO",
                "departure_at": "2026-07-23T08:10:00+08:00",
                "arrival_at": "2026-07-23T09:45:00+08:00",
                "fares": [
                    {
                        "fare_id": "mu6863_economy_1_68000",
                        "cabin_type": "ECONOMY",
                        "price": {"amount_minor": 68000, "currency": "CNY", "scale": 2},
                        "availability": "LIMITED",
                        "remaining_count": 4,
                    }
                ],
            }
        ],
        "evidence_id": "mubw_test_evidence",
        "cache_hit": False,
        "queue_ms": 2,
        "navigation_ms": 1500,
        "response_ms": 1500,
        "parse_ms": 4,
        "total_ms": 1506,
    }


def _provider(payload: dict, tmp_path) -> tuple[BrowserAirlineFlightProvider, _FakeHttpClient]:
    http_client = _FakeHttpClient(payload)
    worker_client = BrowserWorkerClient(
        worker_url="http://127.0.0.1:4319",
        allowed_hosts=("127.0.0.1",),
        timeout_seconds=20,
        client=http_client,
    )
    provider = BrowserAirlineFlightProvider(
        source_id="airline_mu_browser_query",
        client=worker_client,
        cache_ttl_seconds=90,
        snapshot_backend="sqlite",
        snapshot_sqlite_path=tmp_path / "flight.sqlite3",
    )
    return provider, http_client


def test_browser_worker_client_rejects_non_loopback_url() -> None:
    with pytest.raises(BrowserWorkerClientError, match="internal HTTP|loopback"):
        BrowserWorkerClient(
            worker_url="https://worker.example.com",
            allowed_hosts=("worker.example.com",),
            timeout_seconds=20,
        )


def test_browser_provider_maps_verified_worker_result(tmp_path) -> None:
    provider, http_client = _provider(_success_payload(), tmp_path)

    offers = provider.search_offers(
        FlightSearchRequest(
            origin_iata="PVG",
            destination_iata="TAO",
            departure_date=date(2026, 7, 23),
            adults=1,
            currency_code="CNY",
            max_results=5,
        )
    )

    assert len(offers) == 1
    assert offers[0].segments[0].carrier_code == "MU"
    assert offers[0].segments[0].flight_number == "6863"
    assert offers[0].total_price.amount_minor == 68000
    assert offers[0].cabin_options[0].remaining_count == 4
    assert http_client.requests[0]["url"] == "http://127.0.0.1:4319/v1/flight-search"


def test_browser_provider_fails_closed_on_challenge(tmp_path) -> None:
    payload = {
        "success": False,
        "source_id": "airline_mu_browser_query",
        "flights": [],
        "error_code": "AIRLINE_CAPTCHA",
        "message": "airline challenge page detected",
        "retryable": True,
        "challenge": {"code": "CAPTCHA", "message": "airline challenge page detected"},
        "queue_ms": 0,
        "navigation_ms": 0,
        "response_ms": 0,
        "parse_ms": 0,
        "total_ms": 5000,
    }
    provider, _ = _provider(payload, tmp_path)

    with pytest.raises(FlightProviderError, match="AIRLINE_CAPTCHA"):
        provider.search_offers(
            FlightSearchRequest(
                origin_iata="PVG",
                destination_iata="TAO",
                departure_date=date(2026, 7, 23),
            )
        )


def test_browser_provider_rejects_route_mismatch(tmp_path) -> None:
    payload = _success_payload()
    payload["flights"][0]["destination_iata"] = "PEK"
    provider, _ = _provider(payload, tmp_path)

    with pytest.raises(FlightProviderError, match="mismatched route"):
        provider.search_offers(
            FlightSearchRequest(
                origin_iata="PVG",
                destination_iata="TAO",
                departure_date=date(2026, 7, 23),
            )
        )
