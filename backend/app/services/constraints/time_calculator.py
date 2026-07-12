from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from zoneinfo import ZoneInfo

from app.models.schemas import ConstraintType, ConstraintViolation, DurationDeviation, FlightSegment, RailSegment, TimePoint, TravelPlan, TravelRequest


def _utc_datetime(point: TimePoint) -> datetime:
    value = point.datetime
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(point.timezone))
    return value.astimezone(timezone.utc)


def _is_before(left: TimePoint, right: TimePoint) -> bool:
    return _utc_datetime(left) < _utc_datetime(right)


def _is_after(left: TimePoint, right: TimePoint) -> bool:
    return _utc_datetime(left) > _utc_datetime(right)


def _minutes_between(actual: TimePoint, requested: TimePoint) -> int:
    return max(0, ceil(abs((_utc_datetime(actual) - _utc_datetime(requested)).total_seconds()) / 60))


def _violation(
    constraint_type: ConstraintType,
    requested: TimePoint,
    actual: TimePoint,
    direction: str,
    reason_code: str,
    message: str,
) -> ConstraintViolation:
    return ConstraintViolation(
        constraint_type=constraint_type,
        requested_value=requested.model_dump(mode="json"),
        actual_value=actual.model_dump(mode="json"),
        deviation=DurationDeviation(value=_minutes_between(actual, requested), direction=direction),
        reason_code=reason_code,
        user_visible_message=message,
    )


def evaluate_time_constraints(plan: TravelPlan, request: TravelRequest) -> tuple[list[ConstraintViolation], list[ConstraintType]]:
    violations: list[ConstraintViolation] = []
    preserved: list[ConstraintType] = []
    main_segments = [segment for segment in plan.segments if isinstance(segment, (RailSegment, FlightSegment))]
    departure = main_segments[0].departure_time if main_segments else plan.departure_time
    arrival = main_segments[-1].arrival_time if main_segments else plan.arrival_time
    earliest = request.hard_constraints.earliest_departure_time or request.earliest_departure_time
    latest = request.hard_constraints.latest_arrival_time or request.latest_arrival_time

    if earliest and departure:
        if _is_before(departure, earliest):
            minutes = _minutes_between(departure, earliest)
            violations.append(_violation(ConstraintType.EARLIEST_DEPARTURE, earliest, departure, "EARLIER", "TIME_CONSTRAINT_TOO_EARLY", f"该方案比最早出发时间提前{minutes}分钟。"))
        else:
            preserved.append(ConstraintType.EARLIEST_DEPARTURE)
    if latest and arrival:
        if _is_after(arrival, latest):
            minutes = _minutes_between(arrival, latest)
            violations.append(_violation(ConstraintType.LATEST_ARRIVAL, latest, arrival, "LATER", "TIME_CONSTRAINT_TOO_LATE", f"该方案预计{arrival.datetime:%H:%M}到达，比期望时间晚{minutes}分钟。"))
        else:
            preserved.append(ConstraintType.LATEST_ARRIVAL)

    if request.time_anchor_type == "ARRIVAL" and arrival:
        if request.time_window_start and _is_before(arrival, request.time_window_start):
            minutes = _minutes_between(arrival, request.time_window_start)
            violations.append(_violation(ConstraintType.ARRIVAL_TIME_WINDOW, request.time_window_start, arrival, "EARLIER", "ARRIVAL_WINDOW_TOO_EARLY", f"该方案比到达时间窗提前{minutes}分钟。"))
        elif request.time_window_end and _is_after(arrival, request.time_window_end) and not latest:
            minutes = _minutes_between(arrival, request.time_window_end)
            violations.append(_violation(ConstraintType.ARRIVAL_TIME_WINDOW, request.time_window_end, arrival, "LATER", "ARRIVAL_WINDOW_TOO_LATE", f"该方案比到达时间窗晚{minutes}分钟。"))
        elif request.time_window_start or request.time_window_end:
            preserved.append(ConstraintType.ARRIVAL_TIME_WINDOW)
    elif request.time_anchor_type != "ARRIVAL" and departure:
        if request.time_window_start and _is_before(departure, request.time_window_start) and not earliest:
            minutes = _minutes_between(departure, request.time_window_start)
            violations.append(_violation(ConstraintType.DEPARTURE_TIME_WINDOW, request.time_window_start, departure, "EARLIER", "DEPARTURE_WINDOW_TOO_EARLY", f"该方案比出发时间窗提前{minutes}分钟。"))
        elif request.time_window_end and _is_after(departure, request.time_window_end):
            minutes = _minutes_between(departure, request.time_window_end)
            violations.append(_violation(ConstraintType.DEPARTURE_TIME_WINDOW, request.time_window_end, departure, "LATER", "DEPARTURE_WINDOW_TOO_LATE", f"该方案比出发时间窗晚{minutes}分钟。"))
        elif request.time_window_start or request.time_window_end:
            preserved.append(ConstraintType.DEPARTURE_TIME_WINDOW)
    return violations, preserved
