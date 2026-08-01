from __future__ import annotations

from hashlib import sha256

from app.models.schemas import RailSegment, SeatOption, TravelPlan, TravelRequest
from app.services.cost_comfort_risk_engine import (
    rail_seat_comfort_rank,
    refresh_plan_variant_scores,
)
from app.services.result_set_preferences import normalize_seat_type

AVAILABLE_SEAT_STATUSES = {"AVAILABLE", "LIMITED"}
VARIANT_LABELS = {
    "COST_OPTIMIZED": "省预算",
    "COMFORT_OPTIMIZED": "更舒适",
    "BALANCED": "均衡",
    "PREFERRED": "指定席别",
}


def materialize_rail_plan_variants(
    plans: list[TravelPlan],
    request: TravelRequest,
    *,
    max_variants_per_plan: int = 3,
) -> list[TravelPlan]:
    materialized: list[TravelPlan] = []
    for plan in plans:
        materialized.extend(
            materialize_rail_plan_variant(
                plan,
                request,
                max_variants=max_variants_per_plan,
            )
        )
    return materialized


def materialize_rail_plan_variant(
    plan: TravelPlan,
    request: TravelRequest,
    *,
    max_variants: int = 3,
) -> list[TravelPlan]:
    rail_segments = [segment for segment in plan.segments if isinstance(segment, RailSegment)]
    if not rail_segments or max_variants <= 0:
        return [plan]

    available_by_segment = {
        segment.segment_id: _available_seats(segment)
        for segment in rail_segments
    }
    if any(not options for options in available_by_segment.values()):
        return [plan]

    selections: list[tuple[str, dict[str, SeatOption]]] = []
    preferred = request.preferred_rail_seat
    if preferred:
        preferred_selection = _preferred_selection(available_by_segment, preferred)
        if preferred_selection is not None:
            selections.append(("PREFERRED", preferred_selection))
        else:
            selections.append(("COST_OPTIMIZED", _cost_selection(available_by_segment)))
    else:
        selections.extend(
            (
                ("COST_OPTIMIZED", _cost_selection(available_by_segment)),
                (
                    "COMFORT_OPTIMIZED",
                    _comfort_selection(plan, available_by_segment, request),
                ),
                ("BALANCED", _balanced_selection(available_by_segment)),
            )
        )

    variants: list[TravelPlan] = []
    seen_fingerprints: set[str] = set()
    for strategy, selected_by_segment in selections:
        fingerprint = _selection_fingerprint(selected_by_segment)
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        variant = plan.model_copy(deep=True)
        for segment in variant.segments:
            if isinstance(segment, RailSegment):
                segment.selected_seat_option_id = selected_by_segment[segment.segment_id].option_id
        digest = sha256(fingerprint.encode("utf-8")).hexdigest()[:10]
        variant.plan_id = f"{plan.plan_id}__{strategy.lower()}_{digest}"
        variant.plan_name = f"{plan.plan_name} · {VARIANT_LABELS[strategy]}"
        refresh_plan_variant_scores(variant, plan)
        variants.append(variant)
        if len(variants) >= max_variants:
            break
    return variants or [plan]


def select_lowest_available_seat(options: list[SeatOption]) -> SeatOption:
    available = [
        option for option in options
        if option.availability in AVAILABLE_SEAT_STATUSES and option.price.amount_minor > 0
    ]
    if not available:
        raise ValueError("rail offer has no priced available seat")
    return min(available, key=lambda option: (option.price.amount_minor, option.option_id))


def _available_seats(segment: RailSegment) -> list[SeatOption]:
    return sorted(
        (
            option for option in segment.seat_options
            if option.availability in AVAILABLE_SEAT_STATUSES and option.price.amount_minor > 0
        ),
        key=lambda option: (option.price.amount_minor, option.option_id),
    )


def _cost_selection(available_by_segment: dict[str, list[SeatOption]]) -> dict[str, SeatOption]:
    return {
        segment_id: min(options, key=lambda option: (option.price.amount_minor, option.option_id))
        for segment_id, options in available_by_segment.items()
    }


def _comfort_selection(
    plan: TravelPlan,
    available_by_segment: dict[str, list[SeatOption]],
    request: TravelRequest,
) -> dict[str, SeatOption]:
    selected = {
        segment_id: max(
            options,
            key=lambda option: (
                rail_seat_comfort_rank(option.seat_type),
                -option.price.amount_minor,
                option.option_id,
            ),
        )
        for segment_id, options in available_by_segment.items()
    }
    budget = request.hard_constraints.max_total_cost
    if budget is None or budget.currency != "CNY" or budget.scale != 2:
        return selected

    non_rail_cost = plan.cost_breakdown.total_cost.amount_minor
    for segment in plan.segments:
        if isinstance(segment, RailSegment):
            current = next(option for option in segment.seat_options if option.option_id == segment.selected_seat_option_id)
            non_rail_cost -= current.price.amount_minor

    while non_rail_cost + sum(option.price.amount_minor for option in selected.values()) > budget.amount_minor:
        downgrade_candidates: list[tuple[float, int, str, SeatOption]] = []
        for segment_id, current in selected.items():
            current_rank = rail_seat_comfort_rank(current.seat_type)
            for option in available_by_segment[segment_id]:
                saving = current.price.amount_minor - option.price.amount_minor
                comfort_loss = current_rank - rail_seat_comfort_rank(option.seat_type)
                if saving <= 0 or comfort_loss < 0:
                    continue
                downgrade_candidates.append(
                    (comfort_loss / saving, -saving, segment_id, option)
                )
        if not downgrade_candidates:
            break
        _, _, segment_id, replacement = min(
            downgrade_candidates,
            key=lambda item: (item[0], item[1], item[2], item[3].option_id),
        )
        selected[segment_id] = replacement
    return selected


def _balanced_selection(available_by_segment: dict[str, list[SeatOption]]) -> dict[str, SeatOption]:
    selected: dict[str, SeatOption] = {}
    for segment_id, options in available_by_segment.items():
        min_price = min(option.price.amount_minor for option in options)
        max_price = max(option.price.amount_minor for option in options)
        min_rank = min(rail_seat_comfort_rank(option.seat_type) for option in options)
        max_rank = max(rail_seat_comfort_rank(option.seat_type) for option in options)

        def balanced_key(option: SeatOption) -> tuple[float, int, int, str]:
            price_span = max(1, max_price - min_price)
            rank_span = max(1, max_rank - min_rank)
            normalized_price = (option.price.amount_minor - min_price) / price_span
            normalized_comfort_loss = (
                max_rank - rail_seat_comfort_rank(option.seat_type)
            ) / rank_span
            return (
                normalized_price + normalized_comfort_loss,
                option.price.amount_minor,
                -rail_seat_comfort_rank(option.seat_type),
                option.option_id,
            )

        selected[segment_id] = min(options, key=balanced_key)
    return selected


def _preferred_selection(
    available_by_segment: dict[str, list[SeatOption]],
    preferred_seat: str,
) -> dict[str, SeatOption] | None:
    normalized_preferred = normalize_seat_type(preferred_seat)
    selected: dict[str, SeatOption] = {}
    for segment_id, options in available_by_segment.items():
        matches = [
            option for option in options
            if normalize_seat_type(option.seat_type) == normalized_preferred
        ]
        if not matches:
            return None
        selected[segment_id] = min(
            matches,
            key=lambda option: (option.price.amount_minor, option.option_id),
        )
    return selected


def _selection_fingerprint(selected_by_segment: dict[str, SeatOption]) -> str:
    return "|".join(
        f"{segment_id}:{selected_by_segment[segment_id].option_id}"
        for segment_id in sorted(selected_by_segment)
    )
