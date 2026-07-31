from __future__ import annotations

from app.models.schemas import TravelPlan, TravelRequest
from app.services.constraints.budget_calculator import evaluate_budget_constraint
from app.services.constraints.models import ConstraintEvaluationResult
from app.services.constraints.safety_gate import relaxation_safety_reason
from app.services.constraints.seat_cabin_calculator import evaluate_seat_cabin_constraints
from app.services.constraints.time_calculator import evaluate_time_constraints
from app.services.constraints.transport_mode_calculator import evaluate_transport_constraints


def evaluate_plan_constraints(plan: TravelPlan, request: TravelRequest) -> ConstraintEvaluationResult:
    safety_reason = relaxation_safety_reason(plan)
    has_departure_constraint = bool(
        request.hard_constraints.earliest_departure_time
        or request.earliest_departure_time
        or (request.time_anchor_type != "ARRIVAL" and (request.time_window_start or request.time_window_end))
    )
    has_arrival_constraint = bool(
        request.hard_constraints.latest_arrival_time
        or request.latest_arrival_time
        or (request.time_anchor_type == "ARRIVAL" and (request.time_window_start or request.time_window_end))
    )
    if safety_reason is None and (
        (has_departure_constraint and plan.departure_time is None)
        or (has_arrival_constraint and plan.arrival_time is None)
    ):
        safety_reason = "DOOR_TO_DOOR_TIME_MISSING"
    violations = []
    preserved = []
    for calculator in (
        evaluate_time_constraints,
        evaluate_budget_constraint,
        evaluate_transport_constraints,
        evaluate_seat_cabin_constraints,
    ):
        next_violations, next_preserved = calculator(plan, request)
        violations.extend(next_violations)
        preserved.extend(next_preserved)
    return ConstraintEvaluationResult(
        plan=plan,
        violations=tuple(violations),
        preserved_constraints=tuple(dict.fromkeys(preserved)),
        safe_for_relaxation=safety_reason is None,
        safety_reason=safety_reason,
    )
