import httpx
import pytest

from app.data_sources.rate_limiter import ProviderRateLimiter, RateLimitedHttpClient
from app.data_sources.provider_registry import build_enabled_providers


class _ManualTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_provider_rate_limiter_enforces_qps_per_source() -> None:
    manual = _ManualTime()
    limiter = ProviderRateLimiter(clock=manual.clock, sleeper=manual.sleep)

    limiter.wait("source_a", 2)
    limiter.wait("source_a", 2)
    limiter.wait("source_b", 2)

    assert manual.sleeps == [0.5]


def test_rate_limited_http_client_applies_limit_to_real_request_boundary() -> None:
    manual = _ManualTime()
    limiter = ProviderRateLimiter(clock=manual.clock, sleeper=manual.sleep)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, request=request))

    with RateLimitedHttpClient(
        source_id="source_a",
        qps_limit=4,
        rate_limiter=limiter,
        transport=transport,
    ) as client:
        client.get("https://example.test/first")
        client.get("https://example.test/second")

    assert manual.sleeps == [0.25]


def test_provider_rate_limiter_uses_stricter_minimum_interval() -> None:
    manual = _ManualTime()
    limiter = ProviderRateLimiter(clock=manual.clock, sleeper=manual.sleep)

    limiter.wait("rail", 10, min_interval_seconds=1.0)
    limiter.wait("rail", 10, min_interval_seconds=1.0)

    assert manual.sleeps == [1.0]


def test_provider_rate_limiter_rejects_non_positive_limit() -> None:
    limiter = ProviderRateLimiter()

    with pytest.raises(ValueError, match="positive"):
        limiter.wait("source_a", 0)


def test_enabled_http_provider_factories_use_rate_limited_clients() -> None:
    providers = build_enabled_providers(
        {
            "osrm_route",
            "nominatim_geocode",
            "opensky_states",
            "open_meteo_forecast",
            "rail_12306_public_query",
        },
        "DEV",
    )
    try:
        assert len(providers) == 5
        assert all(isinstance(provider.client, RateLimitedHttpClient) for provider in providers)
    finally:
        for provider in providers:
            provider.client.close()
