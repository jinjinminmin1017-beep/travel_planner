from __future__ import annotations

from app.models.schemas import ConstraintType, ConstraintViolation, MoneyDeviation, TravelPlan, TravelRequest


def evaluate_budget_constraint(plan: TravelPlan, request: TravelRequest) -> tuple[list[ConstraintViolation], list[ConstraintType]]:
    budget = request.hard_constraints.max_total_cost
    if budget is None:
        return [], []
    actual = plan.cost_breakdown.total_cost
    if actual.currency != budget.currency or actual.scale != budget.scale:
        return [], []
    if actual.amount_minor <= budget.amount_minor:
        return [], [ConstraintType.MAX_TOTAL_COST]
    delta = actual.amount_minor - budget.amount_minor
    factor = 10 ** actual.scale
    major, minor = divmod(delta, factor)
    display_delta = f"{major}.{minor:0{actual.scale}d}" if actual.scale else str(major)
    return [ConstraintViolation(
        constraint_type=ConstraintType.MAX_TOTAL_COST,
        requested_value=budget.model_dump(mode="json"),
        actual_value=actual.model_dump(mode="json"),
        deviation=MoneyDeviation(amount_minor=delta, currency=actual.currency, scale=actual.scale),
        reason_code="BUDGET_CONSTRAINT_EXCEEDED",
        user_visible_message=f"该方案超出预算¥{display_delta}。",
    )], []
