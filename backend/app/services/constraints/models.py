from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import ConstraintType, ConstraintViolation, TravelPlan


@dataclass(frozen=True)
class ConstraintEvaluationResult:
    plan: TravelPlan
    violations: tuple[ConstraintViolation, ...]
    preserved_constraints: tuple[ConstraintType, ...]
    safe_for_relaxation: bool
    safety_reason: str | None = None

    @property
    def satisfies_all(self) -> bool:
        return self.safe_for_relaxation and not self.violations
