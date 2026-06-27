from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

DEFAULT_ASYNC_JOB_TTL_SECONDS = 1800
DEFAULT_RECALCULATE_TTL_SECONDS = 900

_CACHE: dict[str, tuple[datetime, str]] = {}


def async_job_ttl_seconds() -> int:
    return int(os.getenv("TRAVEL_CACHE_ASYNC_JOB_TTL_SECONDS", str(DEFAULT_ASYNC_JOB_TTL_SECONDS)))


def recalculate_ttl_seconds() -> int:
    return int(os.getenv("TRAVEL_CACHE_RECALCULATE_TTL_SECONDS", str(DEFAULT_RECALCULATE_TTL_SECONDS)))


def set_json(key: str, value: str, ttl_seconds: int) -> None:
    _CACHE[key] = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds), value)


def get_json(key: str) -> str | None:
    item = _CACHE.get(key)
    if item is None:
        return None
    expires_at, value = item
    if expires_at <= datetime.now(timezone.utc):
        _CACHE.pop(key, None)
        return None
    return value


def delete_expired() -> None:
    now = datetime.now(timezone.utc)
    expired = [key for key, (expires_at, _) in _CACHE.items() if expires_at <= now]
    for key in expired:
        _CACHE.pop(key, None)
