from __future__ import annotations

import logging
import os
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.data_sources.rail_providers import RailOffer, station_code_for_name
from app.models.schemas import LocalTransferSegment

logger = logging.getLogger("app.planner.rail_connection")

SHANGHAI_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RailConnectionPolicy:
    min_same_station_transfer_minutes: int = 45
    max_transfer_wait_minutes: int = 360
    max_connections_per_first_offer: int = 4
    max_raw_connections_per_hub: int = 24
    allow_overnight_transfer: bool = False
    cross_station_exit_buffer_minutes: int = 15
    cross_station_entry_buffer_minutes: int = 15


@dataclass(frozen=True)
class RailConnectionCandidate:
    first_offer: RailOffer
    second_offer: RailOffer
    same_station: bool
    wait_minutes: int
    required_transfer_minutes: int
    cross_station_transfer: LocalTransferSegment | None
    stable_key: str


@dataclass
class RailConnectionMetrics:
    first_offer_count: int = 0
    second_offer_count: int = 0
    pairs_examined: int = 0
    rejected_departed_before_arrival: int = 0
    rejected_transfer_buffer: int = 0
    rejected_max_wait: int = 0
    rejected_cross_station_route: int = 0
    rejected_invalid_fact: int = 0
    rejected_overnight: int = 0
    valid_connection_count: int = 0


CrossStationTransferResolver = Callable[[RailOffer, RailOffer], LocalTransferSegment | None]


def rail_connection_matcher_v2_enabled() -> bool:
    raw_value = os.getenv("TRAVEL_RAIL_CONNECTION_MATCHER_V2", "true")
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.error(
        "rail_connection_config_invalid config=TRAVEL_RAIL_CONNECTION_MATCHER_V2 value=%r fallback=true",
        raw_value,
    )
    return True


def rail_connection_policy_from_env() -> RailConnectionPolicy:
    min_transfer_minutes = _positive_int_env("TRAVEL_RAIL_MIN_TRANSFER_MINUTES", 45)
    max_wait_minutes = _positive_int_env("TRAVEL_RAIL_MAX_TRANSFER_WAIT_MINUTES", 360)
    if max_wait_minutes < min_transfer_minutes:
        safe_max_wait = max(360, min_transfer_minutes)
        logger.error(
            "rail_connection_config_invalid config=TRAVEL_RAIL_MAX_TRANSFER_WAIT_MINUTES value=%s reason=below_min_transfer fallback=%s",
            max_wait_minutes,
            safe_max_wait,
        )
        max_wait_minutes = safe_max_wait
    return RailConnectionPolicy(
        min_same_station_transfer_minutes=min_transfer_minutes,
        max_transfer_wait_minutes=max_wait_minutes,
    )


def match_rail_connections(
    first_offers: list[RailOffer],
    second_offers: list[RailOffer],
    *,
    policy: RailConnectionPolicy,
    resolve_cross_station_transfer: CrossStationTransferResolver,
) -> tuple[list[RailConnectionCandidate], RailConnectionMetrics]:
    first = _deduplicate_offers(first_offers, time_field="arrival")
    second = _deduplicate_offers(second_offers, time_field="departure")
    metrics = RailConnectionMetrics(first_offer_count=len(first), second_offer_count=len(second))
    if not first or not second:
        return [], metrics

    second_groups = _group_second_offers(second)
    raw_candidates: list[RailConnectionCandidate] = []
    for first_offer in first:
        first_candidates: list[RailConnectionCandidate] = []
        first_arrival = _normalized_datetime(first_offer.arrival_at)
        for group_offers in second_groups.values():
            representative = group_offers[0]
            same_station = _same_station(first_offer, representative)
            cross_station_transfer: LocalTransferSegment | None = None
            required_minutes = policy.min_same_station_transfer_minutes
            if not same_station:
                cross_station_transfer = resolve_cross_station_transfer(first_offer, representative)
                if cross_station_transfer is None:
                    metrics.rejected_cross_station_route += len(group_offers)
                    continue
                required_minutes = max(
                    policy.min_same_station_transfer_minutes,
                    policy.cross_station_exit_buffer_minutes
                    + cross_station_transfer.duration_minutes
                    + policy.cross_station_entry_buffer_minutes,
                )

            departure_times = [_normalized_datetime(offer.departure_at) for offer in group_offers]
            arrival_index = bisect_left(departure_times, first_arrival)
            earliest_departure = first_arrival + timedelta(minutes=required_minutes)
            earliest_index = bisect_left(departure_times, earliest_departure)
            latest_departure = first_arrival + timedelta(minutes=policy.max_transfer_wait_minutes)
            latest_index = bisect_right(departure_times, latest_departure)
            metrics.rejected_departed_before_arrival += arrival_index
            metrics.rejected_transfer_buffer += max(0, earliest_index - arrival_index)
            metrics.rejected_max_wait += max(0, len(group_offers) - latest_index)

            for second_offer in group_offers[earliest_index:latest_index]:
                metrics.pairs_examined += 1
                if not _valid_offer(first_offer) or not _valid_offer(second_offer):
                    metrics.rejected_invalid_fact += 1
                    continue
                if first_offer.train_number.strip().upper() == second_offer.train_number.strip().upper():
                    metrics.rejected_invalid_fact += 1
                    continue
                second_departure = _normalized_datetime(second_offer.departure_at)
                if not policy.allow_overnight_transfer and second_departure.date() != first_arrival.date():
                    metrics.rejected_overnight += 1
                    continue
                wait_minutes = int((second_departure - first_arrival).total_seconds() // 60)
                stable_key = _connection_stable_key(first_offer, second_offer)
                first_candidates.append(
                    RailConnectionCandidate(
                        first_offer=first_offer,
                        second_offer=second_offer,
                        same_station=same_station,
                        wait_minutes=wait_minutes,
                        required_transfer_minutes=required_minutes,
                        cross_station_transfer=cross_station_transfer,
                        stable_key=stable_key,
                    )
                )

        first_candidates.sort(key=_candidate_sort_key)
        metrics.valid_connection_count += len(first_candidates)
        raw_candidates.extend(first_candidates[: policy.max_connections_per_first_offer])

    unique_candidates = {candidate.stable_key: candidate for candidate in raw_candidates}
    ordered = sorted(unique_candidates.values(), key=_candidate_sort_key)
    return ordered[: policy.max_raw_connections_per_hub], metrics


def _group_second_offers(offers: list[RailOffer]) -> dict[str, list[RailOffer]]:
    groups: dict[str, list[RailOffer]] = {}
    for offer in offers:
        identity = _station_identity(offer.origin_station_code, offer.origin_station)
        group_key = identity or f"unknown:{_normalize_station_name(offer.origin_station)}"
        groups.setdefault(group_key, []).append(offer)
    for group in groups.values():
        group.sort(key=lambda offer: (_normalized_datetime(offer.departure_at), _offer_stable_key(offer)))
    return groups


def _same_station(first_offer: RailOffer, second_offer: RailOffer) -> bool:
    first_identity = _station_identity(first_offer.destination_station_code, first_offer.destination_station)
    second_identity = _station_identity(second_offer.origin_station_code, second_offer.origin_station)
    return bool(first_identity and second_identity and first_identity == second_identity)


def _station_identity(explicit_code: str | None, station_name: str) -> str | None:
    station_code = explicit_code or station_code_for_name(station_name)
    normalized = str(station_code or "").strip().upper()
    return f"station_code:{normalized}" if normalized else None


def _deduplicate_offers(offers: list[RailOffer], *, time_field: str) -> list[RailOffer]:
    unique = {_offer_stable_key(offer): offer for offer in offers}
    if time_field == "arrival":
        return sorted(
            unique.values(),
            key=lambda offer: (
                _normalized_datetime(offer.arrival_at),
                _normalized_datetime(offer.departure_at),
                _offer_stable_key(offer),
            ),
        )
    return sorted(
        unique.values(),
        key=lambda offer: (
            _normalized_datetime(offer.departure_at),
            _normalized_datetime(offer.arrival_at),
            _offer_stable_key(offer),
        ),
    )


def _valid_offer(offer: RailOffer) -> bool:
    if not offer.train_number.strip() or not offer.origin_station.strip() or not offer.destination_station.strip():
        return False
    if _normalized_datetime(offer.arrival_at) <= _normalized_datetime(offer.departure_at):
        return False
    if not offer.data_source or not offer.data_source.source_id:
        return False
    return any(
        seat.availability in {"AVAILABLE", "LIMITED"} and seat.price.amount_minor > 0
        for seat in offer.seat_options
    )


def _candidate_sort_key(candidate: RailConnectionCandidate) -> tuple[datetime, int, int, str]:
    total_duration = int(
        (
            _normalized_datetime(candidate.second_offer.arrival_at)
            - _normalized_datetime(candidate.first_offer.departure_at)
        ).total_seconds()
        // 60
    )
    total_cost = _lowest_fare(candidate.first_offer) + _lowest_fare(candidate.second_offer)
    return (
        _normalized_datetime(candidate.second_offer.arrival_at),
        total_duration,
        candidate.wait_minutes,
        f"{total_cost:012d}:{candidate.stable_key}",
    )


def _lowest_fare(offer: RailOffer) -> int:
    prices = [
        seat.price.amount_minor
        for seat in offer.seat_options
        if seat.availability in {"AVAILABLE", "LIMITED"} and seat.price.amount_minor > 0
    ]
    return min(prices) if prices else 2**31 - 1


def _connection_stable_key(first_offer: RailOffer, second_offer: RailOffer) -> str:
    return "|".join(
        (
            first_offer.train_number.strip().upper(),
            _station_fact_key(first_offer.origin_station_code, first_offer.origin_station),
            _station_fact_key(first_offer.destination_station_code, first_offer.destination_station),
            _normalized_datetime(first_offer.departure_at).isoformat(),
            _normalized_datetime(first_offer.arrival_at).isoformat(),
            second_offer.train_number.strip().upper(),
            _station_fact_key(second_offer.origin_station_code, second_offer.origin_station),
            _station_fact_key(second_offer.destination_station_code, second_offer.destination_station),
            _normalized_datetime(second_offer.departure_at).isoformat(),
            _normalized_datetime(second_offer.arrival_at).isoformat(),
        )
    )


def _offer_stable_key(offer: RailOffer) -> str:
    return "|".join(
        (
            offer.train_number.strip().upper(),
            _station_fact_key(offer.origin_station_code, offer.origin_station),
            _station_fact_key(offer.destination_station_code, offer.destination_station),
            _normalized_datetime(offer.departure_at).isoformat(),
            _normalized_datetime(offer.arrival_at).isoformat(),
        )
    )


def _station_fact_key(explicit_code: str | None, station_name: str) -> str:
    return _station_identity(explicit_code, station_name) or f"station_name:{_normalize_station_name(station_name)}"


def _normalize_station_name(value: str) -> str:
    return "".join(str(value or "").strip().lower().split())


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        value = 0
    if value <= 0:
        logger.error("rail_connection_config_invalid config=%s value=%r fallback=%s", name, raw_value, default)
        return default
    return value
