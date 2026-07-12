from __future__ import annotations

from app.models.schemas import CategoricalDeviation, ConstraintType, ConstraintViolation, FlightSegment, RailSegment, TravelPlan, TravelRequest


def evaluate_seat_cabin_constraints(plan: TravelPlan, request: TravelRequest) -> tuple[list[ConstraintViolation], list[ConstraintType]]:
    violations: list[ConstraintViolation] = []
    preserved: list[ConstraintType] = []
    if request.preferred_rail_seat:
        rail = next((segment for segment in plan.segments if isinstance(segment, RailSegment)), None)
        selected = next((item.seat_type for item in rail.seat_options if item.option_id == rail.selected_seat_option_id), None) if rail else None
        if selected and selected != request.preferred_rail_seat:
            violations.append(_categorical(ConstraintType.PREFERRED_RAIL_SEAT, request.preferred_rail_seat, selected, "PREFERRED_RAIL_SEAT_UNAVAILABLE", f"该方案当前席别为{selected}，不是期望的{request.preferred_rail_seat}。"))
        elif selected:
            preserved.append(ConstraintType.PREFERRED_RAIL_SEAT)
    if request.preferred_flight_cabin:
        flight = next((segment for segment in plan.segments if isinstance(segment, FlightSegment)), None)
        selected = next((item.cabin_type for item in flight.cabin_options if item.option_id == flight.selected_cabin_option_id), None) if flight else None
        if selected and selected != request.preferred_flight_cabin:
            violations.append(_categorical(ConstraintType.PREFERRED_FLIGHT_CABIN, request.preferred_flight_cabin, selected, "PREFERRED_FLIGHT_CABIN_UNAVAILABLE", f"该方案当前舱位为{selected}，不是期望的{request.preferred_flight_cabin}。"))
        elif selected:
            preserved.append(ConstraintType.PREFERRED_FLIGHT_CABIN)
    return violations, preserved


def _categorical(constraint_type: ConstraintType, requested: str, actual: str, reason: str, message: str) -> ConstraintViolation:
    return ConstraintViolation(
        constraint_type=constraint_type,
        requested_value={"value": requested},
        actual_value={"value": actual},
        deviation=CategoricalDeviation(requested=requested, actual=actual),
        reason_code=reason,
        user_visible_message=message,
    )
