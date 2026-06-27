from __future__ import annotations

import os

DEFAULT_JOB_TIMEOUT_SECONDS = 30
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 10
DEFAULT_PROVIDER_RETRY_COUNT = 1
DEFAULT_MAX_CONCURRENT_JOBS = 4


def job_timeout_seconds() -> int:
    return int(os.getenv("TRAVEL_ASYNC_JOB_TIMEOUT_SECONDS", str(DEFAULT_JOB_TIMEOUT_SECONDS)))


def provider_timeout_seconds() -> int:
    return int(os.getenv("TRAVEL_PROVIDER_TIMEOUT_SECONDS", str(DEFAULT_PROVIDER_TIMEOUT_SECONDS)))


def provider_retry_count() -> int:
    return int(os.getenv("TRAVEL_PROVIDER_RETRY_COUNT", str(DEFAULT_PROVIDER_RETRY_COUNT)))


def max_concurrent_jobs() -> int:
    return int(os.getenv("TRAVEL_MAX_CONCURRENT_JOBS", str(DEFAULT_MAX_CONCURRENT_JOBS)))
