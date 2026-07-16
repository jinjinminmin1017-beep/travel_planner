from __future__ import annotations

from threading import Lock
from time import monotonic, sleep
from typing import Callable

import httpx


class ProviderRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._lock = Lock()
        self._next_slot_at: dict[str, float] = {}

    def wait(
        self,
        source_id: str,
        qps_limit: int,
        min_interval_seconds: float | None = None,
    ) -> None:
        if qps_limit <= 0:
            raise ValueError("qps_limit must be positive")
        interval_seconds = max(1.0 / qps_limit, min_interval_seconds or 0.0)
        with self._lock:
            now = self._clock()
            slot_at = max(now, self._next_slot_at.get(source_id, now))
            self._next_slot_at[source_id] = slot_at + interval_seconds
        delay_seconds = slot_at - now
        if delay_seconds > 0:
            self._sleeper(delay_seconds)

    def reset(self) -> None:
        with self._lock:
            self._next_slot_at.clear()


GLOBAL_PROVIDER_RATE_LIMITER = ProviderRateLimiter()


class RateLimitedHttpClient(httpx.Client):
    def __init__(
        self,
        *,
        source_id: str,
        qps_limit: int,
        min_interval_seconds: float | None = None,
        rate_limiter: ProviderRateLimiter = GLOBAL_PROVIDER_RATE_LIMITER,
        **kwargs: object,
    ) -> None:
        if qps_limit <= 0:
            raise ValueError("qps_limit must be positive")
        super().__init__(**kwargs)
        self._source_id = source_id
        self._qps_limit = qps_limit
        self._min_interval_seconds = min_interval_seconds
        self._rate_limiter = rate_limiter

    def request(self, method: str, url: httpx.URL | str, **kwargs: object) -> httpx.Response:
        self._rate_limiter.wait(
            self._source_id,
            self._qps_limit,
            self._min_interval_seconds,
        )
        return super().request(method, url, **kwargs)
