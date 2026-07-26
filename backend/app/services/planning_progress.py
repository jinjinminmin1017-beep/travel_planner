from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.models.schemas import TravelPlan


@dataclass
class PlanningExecutionMetrics:
    route_cache_hits: int = 0
    route_cache_misses: int = 0
    location_cache_hits: int = 0
    location_cache_misses: int = 0


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
