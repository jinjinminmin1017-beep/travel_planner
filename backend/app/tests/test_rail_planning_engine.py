from app.models.schemas import PlanType, RecommendationEligibility, TicketEnhancementGrade
from app.services.rail_planning_engine import build_rail_plan_specs


def test_shanghai_qingdao_rail_specs_cover_transfer_and_ticket_enhancements():
    specs = build_rail_plan_specs("上海_青岛", "上海虹桥", "青岛北")
    by_id = {spec.plan_id: spec for spec in specs}

    assert {
        "plan_rail_direct_shqd",
        "plan_rail_transfer_shqd",
        "plan_rail_multi_transfer_shqd",
        "plan_ticket_s_shqd",
        "plan_ticket_a_shqd",
        "plan_buy_short_shqd",
        "plan_blocked_shqd",
    }.issubset(by_id)

    transfer_stops = [stop for leg in by_id["plan_rail_transfer_shqd"].legs for stop in leg.stop_sequence]
    multi_stops = [stop for leg in by_id["plan_rail_multi_transfer_shqd"].legs for stop in leg.stop_sequence]
    assert "济南西" in transfer_stops
    assert {"徐州东", "济南西"}.issubset(set(multi_stops))
    assert "中转站" not in transfer_stops
    assert "中转站" not in multi_stops

    assert by_id["plan_ticket_s_shqd"].ticket_enhancement.grade == TicketEnhancementGrade.S
    assert by_id["plan_ticket_a_shqd"].ticket_enhancement.grade == TicketEnhancementGrade.A
    assert by_id["plan_ticket_a_shqd"].eligibility == RecommendationEligibility.NOT_RECOMMENDED
    assert by_id["plan_buy_short_shqd"].ticket_enhancement.grade == TicketEnhancementGrade.NOT_RECOMMENDED
    assert by_id["plan_buy_short_shqd"].ticket_enhancement.requires_onboard_supplement is True
    assert by_id["plan_blocked_shqd"].eligibility == RecommendationEligibility.BLOCKED


def test_beijing_guangzhou_multi_transfer_uses_named_stations():
    specs = build_rail_plan_specs("北京_广州", "北京西", "广州南")
    by_id = {spec.plan_id: spec for spec in specs}
    multi = by_id["plan_rail_multi_transfer_bg"]

    assert multi.plan_type == PlanType.MULTI_TRANSFER_RAIL
    assert [leg.destination_station for leg in multi.legs[:2]] == ["石家庄", "郑州东"]
    assert [leg.origin_station for leg in multi.legs[1:]] == ["石家庄", "郑州东"]
    assert all("中转站" not in leg.stop_sequence for leg in multi.legs)
