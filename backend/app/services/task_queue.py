from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Callable, Literal

DEFAULT_JOB_TIMEOUT_SECONDS = 180
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 10
DEFAULT_PROVIDER_RETRY_COUNT = 1
DEFAULT_MAX_CONCURRENT_JOBS = 4
DeadlineMode = Literal["observe", "enforce"]


def job_timeout_seconds() -> int:
    return max(1, int(os.getenv("TRAVEL_ASYNC_JOB_TIMEOUT_SECONDS", str(DEFAULT_JOB_TIMEOUT_SECONDS))))


def provider_timeout_seconds() -> int:
    return int(os.getenv("TRAVEL_PROVIDER_TIMEOUT_SECONDS", str(DEFAULT_PROVIDER_TIMEOUT_SECONDS)))


def provider_retry_count() -> int:
    return int(os.getenv("TRAVEL_PROVIDER_RETRY_COUNT", str(DEFAULT_PROVIDER_RETRY_COUNT)))


def max_concurrent_jobs() -> int:
    return int(os.getenv("TRAVEL_MAX_CONCURRENT_JOBS", str(DEFAULT_MAX_CONCURRENT_JOBS)))


def progressive_results_enabled() -> bool:
    return os.getenv("TRAVEL_PROGRESSIVE_RESULTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def planning_deadline_mode() -> DeadlineMode:
    configured = os.getenv("TRAVEL_ASYNC_JOB_DEADLINE_MODE", "observe").strip().lower()
    return "enforce" if configured == "enforce" else "observe"


@dataclass
class PlanningDeadline:
    timeout_seconds: float
    mode: DeadlineMode = "observe"
    clock: Callable[[], float] = monotonic
    started_at: float = field(init=False)
    would_timeout: bool = field(default=False, init=False)
    enforced: bool = field(default=False, init=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.timeout_seconds = max(0.001, float(self.timeout_seconds))
        self.started_at = self.clock()

    def remaining_seconds(self) -> float:
        with self._lock:
            return max(0.0, self.timeout_seconds - (self.clock() - self.started_at))

    def allow_new_branch(self, stage: str) -> bool:
        del stage
        with self._lock:
            expired = self.clock() - self.started_at >= self.timeout_seconds
            if not expired:
                return True
            self.would_timeout = True
            if self.mode == "enforce":
                self.enforced = True
                return False
            return True

    def outcome(self, *, has_plans: bool, failed: bool = False) -> str:
        if failed:
            return "ERROR"
        if self.enforced:
            return "ENFORCED_PARTIAL" if has_plans else "ENFORCED_FAILED"
        if self.would_timeout:
            return "WOULD_TIMEOUT"
        return "WITHIN_DEADLINE"


def create_planning_deadline() -> PlanningDeadline:
    return PlanningDeadline(
        timeout_seconds=job_timeout_seconds(),
        mode=planning_deadline_mode(),
    )
