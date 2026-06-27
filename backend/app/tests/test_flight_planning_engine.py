from app.models.schemas import PlanType, RiskLevel
from app.services.flight_planning_engine import build_flight_plan_specs


def test_shanghai_qingdao_flight_specs_cover_direct_transfer_and_multi_airport():
    specs = build_flight_plan_specs("上海_青岛", "上海虹桥机场", "青岛胶东机场")
    by_id = {spec.plan_id: spec for spec in specs}

    assert set(by_id) == {
        "plan_flight_direct_shqd",
        "plan_flight_transfer_shqd",
        "plan_flight_multi_airport_shqd",
    }
    assert by_id["plan_flight_direct_shqd"].plan_type == PlanType.DIRECT_FLIGHT
    assert by_id["plan_flight_transfer_shqd"].plan_type == PlanType.TRANSFER_FLIGHT
    assert by_id["plan_flight_multi_airport_shqd"].plan_type == PlanType.MULTI_AIRPORT_FLIGHT
    assert by_id["plan_flight_multi_airport_shqd"].legs[0].origin_airport == "上海浦东机场"
    assert "重新安检" in by_id["plan_flight_transfer_shqd"].risk_message
    assert "行李" in by_id["plan_flight_transfer_shqd"].risk_message


def test_beijing_guangzhou_flight_specs_use_named_transfer_and_alternate_airport():
    specs = build_flight_plan_specs("北京_广州", "北京首都机场", "广州白云机场")
    by_id = {spec.plan_id: spec for spec in specs}

    transfer = by_id["plan_flight_transfer_bg"]
    multi = by_id["plan_flight_multi_airport_bg"]

    assert transfer.risk_level == RiskLevel.MEDIUM
    assert [leg.destination_airport for leg in transfer.legs] == ["武汉天河机场", "广州白云机场"]
    assert multi.legs[0].origin_airport == "北京大兴机场"
    assert multi.plan_type == PlanType.MULTI_AIRPORT_FLIGHT
