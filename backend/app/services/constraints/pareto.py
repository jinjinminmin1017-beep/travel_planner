from __future__ import annotations

from app.models.schemas import CategoricalDeviation, DurationDeviation, ModeSetDeviation, MoneyDeviation
from app.services.constraints.models import ConstraintEvaluationResult


def _metric_map(item: ConstraintEvaluationResult) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for violation in item.violations:
        deviation = violation.deviation
        if isinstance(deviation, DurationDeviation):
            value = deviation.value
        elif isinstance(deviation, MoneyDeviation):
            value = deviation.amount_minor
        elif isinstance(deviation, ModeSetDeviation):
            value = len(deviation.added_modes) + len(deviation.removed_modes)
        elif isinstance(deviation, CategoricalDeviation):
            value = 1
        else:
            continue
        metrics[violation.constraint_type] = value
    return metrics


def _dominates(left: ConstraintEvaluationResult, right: ConstraintEvaluationResult) -> bool:
    left_metrics = _metric_map(left)
    right_metrics = _metric_map(right)
    all_keys = set(left_metrics) | set(right_metrics)
    if not all_keys:
        return False
    no_worse = all(left_metrics.get(key, 0) <= right_metrics.get(key, 0) for key in all_keys)
    strictly_better = any(left_metrics.get(key, 0) < right_metrics.get(key, 0) for key in all_keys)
    return no_worse and strictly_better


def pareto_frontier(items: list[ConstraintEvaluationResult]) -> list[ConstraintEvaluationResult]:
    return [item for item in items if not any(other is not item and _dominates(other, item) for other in items)]


def violation_metric(item: ConstraintEvaluationResult, kinds: set[str] | None = None) -> int:
    metrics = _metric_map(item)
    selected = [value for key, value in metrics.items() if kinds is None or key in kinds]
    return sum(selected) if selected else 10**12
