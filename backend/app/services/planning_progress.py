from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from time import perf_counter
from typing import Callable, Protocol

from app.models.schemas import TravelPlan


@dataclass
class PlanningExecutionMetrics:
    started_at: float = field(default_factory=perf_counter)
    route_cache_hits: int = 0
    route_cache_misses: int = 0
    location_cache_hits: int = 0
    location_cache_misses: int = 0
    provider_request_count: int = 0
    provider_failure_count: int = 0
    provider_challenge_count: int = 0
    stage_elapsed_ms: dict[str, float] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def mark_stage(self, stage: str) -> None:
        with self._lock:
            self.stage_elapsed_ms.setdefault(stage, round((perf_counter() - self.started_at) * 1000, 1))

    def record_provider_requests(self, count: int = 1) -> None:
        with self._lock:
            self.provider_request_count += max(0, count)

    def record_provider_failure(self, *, challenge: bool = False) -> None:
        with self._lock:
            self.provider_failure_count += 1
            if challenge:
                self.provider_challenge_count += 1

    def safe_summary(self) -> dict[str, object]:
        with self._lock:
            return {
                "stage_elapsed_ms": dict(self.stage_elapsed_ms),
                "provider_request_count": self.provider_request_count,
                "provider_failure_count": self.provider_failure_count,
                "provider_challenge_count": self.provider_challenge_count,
                "route_cache": {"hit": self.route_cache_hits, "miss": self.route_cache_misses},
                "location_cache": {"hit": self.location_cache_hits, "miss": self.location_cache_misses},
            }


@dataclass(frozen=True)
class PlanningProgressUpdate:
    """Domain-only progressive result emitted after normal candidate safety gates."""

    plans: list[TravelPlan] = field(default_factory=list)
    progress: int = 0
    stage: str = "PLANNING"


class PlanningProgressSink(Protocol):
    def publish(self, update: PlanningProgressUpdate) -> None:
        ...


class NoOpPlanningProgressSink:
    def publish(self, update: PlanningProgressUpdate) -> None:
        del update


class CandidateProgressCoordinator:
    """Thread-safe monotonic candidate set for provider-family builders."""

    def __init__(self, publisher: Callable[[list[TravelPlan], int, str], None]) -> None:
        self._publisher = publisher
        self._plans: dict[str, TravelPlan] = {}
        self._progress = 0
        self._lock = RLock()

    def report(self, plan: TravelPlan, *, progress: int, stage: str) -> None:
        with self._lock:
            self._plans[plan.plan_id] = plan.model_copy(deep=True)
            self._progress = max(self._progress, min(progress, 99))
            snapshot = [item.model_copy(deep=True) for item in self._plans.values()]
            current_progress = self._progress
        self._publisher(snapshot, current_progress, stage)
