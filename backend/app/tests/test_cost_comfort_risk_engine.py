from app.core.context import RequestContext
from app.models.schemas import RiskLevel
from app.services.cost_comfort_risk_engine import (
    COMFORT_SCORE_VERSION,
    build_data_quality,
    build_risk_assessment,
    calculate_cost_breakdown,
)
from app.services.intent_parser import parse_travel_request
from app.services.planner import INTERNAL_SOURCE, build_plans


def _request():
    ctx = RequestContext("req_score", "trace_score", "corr_score", "idem_score")
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。",
        ctx,
    )


def _dynamic_plan():
    plans, *_ = build_plans(_request())
    return next(item for item in plans if item.plan_id.startswith("plan_rail_direct_dynamic"))


def test_cost_engine_sums_dynamic_provider_segments():
    plan = _dynamic_plan()

    breakdown = calculate_cost_breakdown(plan.segments, plan.ticket_enhancement)
    item_total = sum(item.amount.amount_minor for item in breakdown.items)

    assert plan.ticket_enhancement is None
    assert breakdown.total_cost.amount_minor == item_total
    assert breakdown.total_cost.amount_minor == plan.cost_breakdown.total_cost.amount_minor


def test_comfort_score_has_version_and_structured_breakdown():
    plan = _dynamic_plan()

    assert plan.comfort_score.score_version == COMFORT_SCORE_VERSION
    assert "换乘复杂度" in plan.comfort_score.breakdown
    assert 0 <= plan.comfort_score.score_vector.comfort <= 1


def test_risk_and_data_quality_support_blocked_outputs():
    risk = build_risk_assessment(RiskLevel.BLOCKED, "安全关键数据缺失", "站序无法确认。", INTERNAL_SOURCE)
    quality = build_data_quality(RiskLevel.BLOCKED, "站序无法确认。", ["rail_stop_sequence"])

    assert risk.overall_risk_level == RiskLevel.BLOCKED
    assert risk.recommendation_allowed is False
    assert quality.completeness_score < 0.5
    assert quality.missing_components == ["rail_stop_sequence"]
    assert quality.warnings