from datetime import datetime, timedelta, timezone

from app.core.context import RequestContext
from app.data_sources.rail_providers import RailOffer, rail_data_source_metadata
from app.data_sources.rail_providers import RailProviderSearchResult
from app.models.schemas import PlanningStatus, SeatOption, TimePoint, TransportMode, money
from app.services.intent_parser import parse_travel_request
from app.services.offer_preselection import OfferPreselectionBucket, preselect_rail_offers
from app.services.planner import plan_trip


SHANGHAI_TZ = timezone(timedelta(hours=8))


def _many_rail_offers() -> list[RailOffer]:
    source = rail_data_source_metadata("rail_12306_public_query", "12306 Public Query")
    offers = []
    start = datetime(2026, 8, 8, 6, 0, tzinfo=SHANGHAI_TZ)
    for index in range(92):
        departure = start + timedelta(minutes=index * 5)
        offers.append(RailOffer(
            train_number=f"G{7000 + index}",
            origin_station="上海虹桥",
            destination_station="温州南",
            departure_at=departure,
            arrival_at=departure + timedelta(hours=3),
            duration_minutes=180,
            stop_sequence=["上海虹桥", "温州南"],
            seat_options=[SeatOption(
                option_id=f"seat_{index}",
                seat_type="二等座",
                price=money(22000),
                availability="AVAILABLE",
                source_option_version=f"fixture_{index}",
                data_source=source,
            )],
            data_source=source,
        ))
    return offers


def test_preselection_scans_all_verified_offers_before_build_budget() -> None:
    context = RequestContext("req_preselect", "trace_preselect", "corr_preselect", "idem_preselect")
    request = parse_travel_request("我 2026 年 8 月 8 日从上海到温州，只坐高铁。", context)
    earliest = TimePoint(
        datetime=datetime(2026, 8, 8, 12, 0, tzinfo=SHANGHAI_TZ),
        timezone="Asia/Shanghai",
        source_timezone="Asia/Shanghai",
    )
    request.earliest_departure_time = earliest
    request.hard_constraints.earliest_departure_time = earliest
    offers = _many_rail_offers()

    result = preselect_rail_offers(offers, request, build_budget=8)

    assert sum(result.counts.values()) == 92
    assert result.counts[OfferPreselectionBucket.RELAXATION_RESERVE.value] > 4
    assert result.buildable[0].bucket == OfferPreselectionBucket.NEEDS_FULL_PLAN
    assert result.buildable[0].offer.departure_at >= earliest.datetime + timedelta(minutes=20)
    assert result.buildable[0].stable_index > 4


def test_full_planner_continues_past_first_four_early_offers(monkeypatch) -> None:
    context = RequestContext("req_full_preselect", "trace_full_preselect", "corr_full_preselect", "idem_full_preselect")
    request = parse_travel_request("我 2026 年 8 月 8 日从上海到温州，只坐高铁。", context)
    earliest = TimePoint(
        datetime=datetime(2026, 8, 8, 12, 0, tzinfo=SHANGHAI_TZ),
        timezone="Asia/Shanghai",
        source_timezone="Asia/Shanghai",
    )
    request.earliest_departure_time = earliest
    request.hard_constraints.earliest_departure_time = earliest
    request.hard_constraints.allowed_transport_modes = [TransportMode.RAIL]
    offers = _many_rail_offers()
    monkeypatch.setattr(
        "app.services.planner.search_rail_offers_with_enabled_provider_result",
        lambda *_args, **_kwargs: RailProviderSearchResult(offers=offers, attempted_source_ids=["rail_12306_public_query"]),
    )

    response = plan_trip(request, context)

    assert response.planning_status in {PlanningStatus.COMPLETE, PlanningStatus.PARTIAL}
    assert response.plans
    assert all(plan.departure_time and plan.departure_time.datetime >= earliest.datetime for plan in response.plans)
    rail_numbers = {
        segment.train_number
        for plan in response.plans
        for segment in plan.segments
        if segment.segment_type == "RAIL"
    }
    assert rail_numbers.isdisjoint({offer.train_number for offer in offers[:4]})
