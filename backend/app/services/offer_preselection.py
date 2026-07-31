from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from app.data_sources.rail_providers import RailOffer
from app.models.schemas import TimePoint, TransportMode, TravelRequest


class OfferPreselectionBucket(str, Enum):
    LIKELY_FEASIBLE = "LIKELY_FEASIBLE"
    NEEDS_FULL_PLAN = "NEEDS_FULL_PLAN"
    RELAXATION_RESERVE = "RELAXATION_RESERVE"
    REJECTED_UNSAFE = "REJECTED_UNSAFE"


@dataclass(frozen=True)
class PreselectedRailOffer:
    offer: RailOffer
    bucket: OfferPreselectionBucket
    reason_codes: tuple[str, ...]
    stable_index: int


@dataclass(frozen=True)
class RailOfferPreselection:
    offers: tuple[PreselectedRailOffer, ...]
    build_budget: int

    @property
    def counts(self) -> dict[str, int]:
        return {
            bucket.value: sum(item.bucket == bucket for item in self.offers)
            for bucket in OfferPreselectionBucket
        }

    @property
    def buildable(self) -> tuple[PreselectedRailOffer, ...]:
        return tuple(item for item in self.offers if item.bucket != OfferPreselectionBucket.REJECTED_UNSAFE)


RAIL_BOARDING_BUFFER_MINUTES = 20
RAIL_ARRIVAL_BUFFER_MINUTES = 10


def preselect_rail_offers(
    offers: list[RailOffer],
    request: TravelRequest,
    *,
    build_budget: int,
    constraint_aware: bool = True,
) -> RailOfferPreselection:
    """Classify every verified rail offer using provider facts only.

    The buffer checks can prove an offer impossible, but never prove that the
    final door-to-door plan satisfies a time constraint. Final acceptance stays
    with the complete-plan constraint evaluator.
    """
    classified = [
        _classify_rail_offer(offer, request, stable_index=index, constraint_aware=constraint_aware)
        for index, offer in enumerate(offers)
    ]
    classified.sort(key=lambda item: _rail_sort_key(item, request))
    return RailOfferPreselection(offers=tuple(classified), build_budget=max(1, build_budget))


def _classify_rail_offer(
    offer: RailOffer,
    request: TravelRequest,
    *,
    stable_index: int,
    constraint_aware: bool,
) -> PreselectedRailOffer:
    if offer.arrival_at <= offer.departure_at or not any(
        seat.availability in {"AVAILABLE", "LIMITED"} for seat in offer.seat_options
    ):
        return PreselectedRailOffer(
            offer=offer,
            bucket=OfferPreselectionBucket.REJECTED_UNSAFE,
            reason_codes=("INVALID_TIME_OR_INVENTORY",),
            stable_index=stable_index,
        )

    if not constraint_aware:
        return PreselectedRailOffer(
            offer=offer,
            bucket=OfferPreselectionBucket.LIKELY_FEASIBLE,
            reason_codes=("CONSTRAINT_PRESELECTION_DISABLED",),
            stable_index=stable_index,
        )

    reasons: list[str] = []
    allowed = set(request.hard_constraints.allowed_transport_modes)
    excluded = set(request.hard_constraints.excluded_transport_modes)
    if (allowed and TransportMode.RAIL not in allowed) or TransportMode.RAIL in excluded:
        reasons.append("TRANSPORT_MODE_CONSTRAINT")

    earliest = request.hard_constraints.earliest_departure_time or request.earliest_departure_time
    latest = request.hard_constraints.latest_arrival_time or request.latest_arrival_time
    if earliest and _as_utc(offer.departure_at) < _point_as_utc(earliest) + timedelta(minutes=RAIL_BOARDING_BUFFER_MINUTES):
        reasons.append("EARLIEST_DEPARTURE_LOWER_BOUND")
    if latest and _as_utc(offer.arrival_at) + timedelta(minutes=RAIL_ARRIVAL_BUFFER_MINUTES) > _point_as_utc(latest):
        reasons.append("LATEST_ARRIVAL_LOWER_BOUND")

    if request.time_anchor_type == "ARRIVAL" and request.time_window_end:
        if _as_utc(offer.arrival_at) > _point_as_utc(request.time_window_end):
            reasons.append("ARRIVAL_WINDOW_END")

    budget = request.hard_constraints.max_total_cost
    priced_seats = [
        seat for seat in offer.seat_options
        if seat.availability in {"AVAILABLE", "LIMITED"}
        and seat.price.currency == (budget.currency if budget else seat.price.currency)
        and seat.price.scale == (budget.scale if budget else seat.price.scale)
    ]
    if budget and priced_seats and min(seat.price.amount_minor for seat in priced_seats) > budget.amount_minor:
        reasons.append("RAIL_FARE_EXCEEDS_TOTAL_BUDGET")

    if request.preferred_rail_seat and not any(
        seat.availability in {"AVAILABLE", "LIMITED"} and seat.seat_type == request.preferred_rail_seat
        for seat in offer.seat_options
    ):
        reasons.append("PREFERRED_RAIL_SEAT_UNAVAILABLE")

    if reasons:
        bucket = OfferPreselectionBucket.RELAXATION_RESERVE
    elif any((earliest, latest, request.time_window_start, request.time_window_end, budget)):
        bucket = OfferPreselectionBucket.NEEDS_FULL_PLAN
    else:
        bucket = OfferPreselectionBucket.LIKELY_FEASIBLE
    return PreselectedRailOffer(
        offer=offer,
        bucket=bucket,
        reason_codes=tuple(reasons),
        stable_index=stable_index,
    )


def _rail_sort_key(item: PreselectedRailOffer, request: TravelRequest) -> tuple:
    priority = {
        OfferPreselectionBucket.LIKELY_FEASIBLE: 0,
        OfferPreselectionBucket.NEEDS_FULL_PLAN: 1,
        OfferPreselectionBucket.RELAXATION_RESERVE: 2,
        OfferPreselectionBucket.REJECTED_UNSAFE: 3,
    }[item.bucket]
    earliest = request.hard_constraints.earliest_departure_time or request.earliest_departure_time
    latest = request.hard_constraints.latest_arrival_time or request.latest_arrival_time
    if earliest:
        distance = abs((_as_utc(item.offer.departure_at) - _point_as_utc(earliest)).total_seconds())
    elif latest:
        distance = abs((_as_utc(item.offer.arrival_at) - _point_as_utc(latest)).total_seconds())
    else:
        distance = item.offer.departure_at.timestamp()
    return priority, distance, item.offer.departure_at, item.offer.train_number, item.stable_index


def _point_as_utc(point: TimePoint) -> datetime:
    value = point.datetime
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(point.timezone))
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
