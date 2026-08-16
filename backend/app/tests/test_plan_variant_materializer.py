from app.core.context import RequestContext
from app.models.schemas import LocalTransferSegment, RailSegment, SeatOption, money
from app.services.cost_comfort_risk_engine import refresh_plan_cost_and_quality
from app.services.intent_parser import parse_travel_request
from app.services.plan_variant_materializer import materialize_rail_plan_variant
from app.services.planner import build_plans


def _rail_fixture_plan():
    ctx = RequestContext("req_variants", "trace_variants", "corr_variants", "idem_variants")
    request = parse_travel_request(
        "2027-05-21 from Shanghai to Qingdao by train",
        ctx,
    )
    request.earliest_departure_time = None
    request.hard_constraints.earliest_departure_time = None
    request.time_window_start = None
    request.time_window_end = None
    plans, *_ = build_plans(request)
    plan = next(
        item for item in plans
        if sum(isinstance(segment, RailSegment) for segment in item.segments) == 1
    ).model_copy(deep=True)
    rail = next(segment for segment in plan.segments if isinstance(segment, RailSegment))
    source = rail.data_source
    rail.train_number = "D3291"
    rail.seat_options = [
        SeatOption(
            option_id="d3291_first",
            seat_type="一等座",
            price=money(41800),
            availability="AVAILABLE",
            source_option_version="fixture_first",
            data_source=source,
        ),
        SeatOption(
            option_id="d3291_second",
            seat_type="二等座",
            price=money(26200),
            availability="AVAILABLE",
            source_option_version="fixture_second",
            data_source=source,
        ),
    ]
    rail.selected_seat_option_id = "d3291_first"
    transfers = [segment for segment in plan.segments if isinstance(segment, LocalTransferSegment)]
    assert len(transfers) == 2
    transfers[0].estimated_cost = money(3200)
    transfers[1].estimated_cost = money(3200)
    refresh_plan_cost_and_quality(plan)
    return plan, request


def test_cost_variant_selects_real_lowest_fare_and_recomputes_total():
    plan, request = _rail_fixture_plan()

    variants = materialize_rail_plan_variant(plan, request)

    cheapest = min(
        variants,
        key=lambda item: item.cost_breakdown.total_cost.amount_minor,
    )
    rail = next(segment for segment in cheapest.segments if isinstance(segment, RailSegment))
    assert rail.selected_seat_option_id == "d3291_second"
    assert cheapest.cost_breakdown.total_cost.amount_minor == 32600
    assert any("D3291 二等座" in item.label for item in cheapest.cost_breakdown.items)
    assert len({variant.plan_id for variant in variants}) == len(variants)
    assert len(variants) <= 3


def test_explicit_first_class_preference_is_not_replaced_by_budget_strategy():
    plan, request = _rail_fixture_plan()
    request.preferred_rail_seat = "一等座"

    variants = materialize_rail_plan_variant(plan, request)

    assert len(variants) == 1
    rail = next(segment for segment in variants[0].segments if isinstance(segment, RailSegment))
    assert rail.selected_seat_option_id == "d3291_first"
    assert variants[0].cost_breakdown.total_cost.amount_minor == 48200


def test_unavailable_explicit_preference_remains_constraint_visible():
    plan, request = _rail_fixture_plan()
    request.preferred_rail_seat = "商务座"

    variants = materialize_rail_plan_variant(plan, request)

    rail = next(segment for segment in variants[0].segments if isinstance(segment, RailSegment))
    assert rail.selected_seat_option_id == "d3291_second"
    assert request.preferred_rail_seat == "商务座"
