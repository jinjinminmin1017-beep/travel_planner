from app.core.context import RequestContext
from app.models.schemas import (
    LocalTransferSegment,
    RecommendationEligibility,
    RiskLevel,
    TicketEnhancementGrade,
)
from app.services.intent_parser import parse_travel_request
from app.services.planner import build_mock_plans
from app.services.planning_rules import (
    assert_option_available,
    blocked_or_backup_plans,
    candidate_plans_for_recommendation,
    has_auxiliary_flight_gap,
)


def _request():
    ctx = RequestContext("req_rules", "trace_rules", "corr_rules", "idem_rules")
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。",
        ctx,
    )


def test_candidate_filter_excludes_blocked_and_backup_ticket_plans():
    plans, *_ = build_mock_plans(_request())
    candidate_ids = {plan.plan_id for plan in candidate_plans_for_recommendation(plans)}
    assert "plan_blocked_shqd" not in candidate_ids
    assert "plan_ticket_a_shqd" not in candidate_ids
    assert "plan_buy_short_shqd" not in candidate_ids
    assert "plan_ticket_s_shqd" in candidate_ids


def test_backup_and_blocked_plans_are_still_explainable():
    plans, *_ = build_mock_plans(_request())
    backup = {plan.plan_id: plan for plan in blocked_or_backup_plans(plans)}
    assert backup["plan_ticket_a_shqd"].recommendation_eligibility == RecommendationEligibility.NOT_RECOMMENDED
    assert backup["plan_blocked_shqd"].risk_assessment.overall_risk_level == RiskLevel.BLOCKED
    assert backup["plan_buy_short_shqd"].ticket_enhancement.grade == TicketEnhancementGrade.NOT_RECOMMENDED


def test_option_validation_and_auxiliary_gap_detection():
    plans, *_ = build_mock_plans(_request())
    direct = next(plan for plan in plans if plan.plan_id == "plan_rail_direct_shqd")
    transfer_flight = next(plan for plan in plans if plan.plan_id == "plan_flight_transfer_shqd")
    rail_segment = next(segment for segment in direct.segments if hasattr(segment, "seat_options"))
    transfer_segment = next(segment for segment in direct.segments if isinstance(segment, LocalTransferSegment))

    assert_option_available(rail_segment, "seat_first")
    assert_option_available(transfer_segment, "transfer_subway")
    assert has_auxiliary_flight_gap(transfer_flight)
