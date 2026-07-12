from __future__ import annotations

from app.models.schemas import ConstraintType, ConstraintViolation, FlightSegment, ModeSetDeviation, RailSegment, TransportMode, TravelPlan, TravelRequest


def main_transport_modes(plan: TravelPlan) -> set[TransportMode]:
    modes: set[TransportMode] = set()
    for segment in plan.segments:
        if isinstance(segment, RailSegment):
            modes.add(TransportMode.RAIL)
        elif isinstance(segment, FlightSegment):
            modes.add(TransportMode.FLIGHT)
    return modes


def _mode_value(mode: TransportMode | str) -> str:
    return mode.value if isinstance(mode, TransportMode) else mode


def evaluate_transport_constraints(plan: TravelPlan, request: TravelRequest) -> tuple[list[ConstraintViolation], list[ConstraintType]]:
    modes = main_transport_modes(plan)
    allowed = set(request.hard_constraints.allowed_transport_modes)
    excluded = set(request.hard_constraints.excluded_transport_modes)
    violations: list[ConstraintViolation] = []
    preserved: list[ConstraintType] = []
    disallowed = modes - allowed if allowed else set()
    if disallowed:
        violations.append(ConstraintViolation(
            constraint_type=ConstraintType.ALLOWED_TRANSPORT_MODES,
            requested_value={"modes": sorted(_mode_value(mode) for mode in allowed)},
            actual_value={"modes": sorted(_mode_value(mode) for mode in modes)},
            deviation=ModeSetDeviation(added_modes=sorted(disallowed, key=_mode_value)),
            reason_code="TRANSPORT_MODE_NOT_ALLOWED",
            user_visible_message=f"该方案需要使用未允许的交通方式：{'、'.join(_mode_value(mode) for mode in sorted(disallowed, key=_mode_value))}。",
        ))
    elif allowed:
        preserved.append(ConstraintType.ALLOWED_TRANSPORT_MODES)
    blocked = modes & excluded
    if blocked:
        violations.append(ConstraintViolation(
            constraint_type=ConstraintType.EXCLUDED_TRANSPORT_MODES,
            requested_value={"excluded_modes": sorted(_mode_value(mode) for mode in excluded)},
            actual_value={"modes": sorted(_mode_value(mode) for mode in modes)},
            deviation=ModeSetDeviation(added_modes=sorted(blocked, key=_mode_value)),
            reason_code="TRANSPORT_MODE_EXCLUDED",
            user_visible_message=f"该方案包含已排除的交通方式：{'、'.join(_mode_value(mode) for mode in sorted(blocked, key=_mode_value))}。",
        ))
    elif excluded:
        preserved.append(ConstraintType.EXCLUDED_TRANSPORT_MODES)
    return violations, preserved
