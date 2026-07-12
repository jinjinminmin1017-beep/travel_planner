from datetime import datetime

import pytest

from app.core.context import RequestContext
from app.models.schemas import PlanningStatus, RecommendationEligibility, RiskLevel, TimePoint, TransportMode, money
from app.services.candidate_generator import generate_candidate_plan_pool
from app.services.constraints.evaluator import evaluate_plan_constraints
from app.services.constraints.relaxation_selector import build_constraint_analysis
from app.services.intent_parser import parse_travel_request
from app.services.planner import build_plans, plan_trip


def _context() -> RequestContext:
    return RequestContext("req_constraints", "trace_constraints", "corr_constraints", "idem_constraints")


def _request():
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店。",
        _context(),
    )


def test_time_no_match_returns_http_business_state_with_safe_alternative(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRAVEL_CONSTRAINT_ANALYSIS_ENABLED", "true")
    request = _request()
    latest = TimePoint(datetime=datetime.fromisoformat("2026-05-21T09:05:00+08:00"), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")
    request.time_anchor_type = "ARRIVAL"
    request.latest_arrival_time = latest
    request.time_window_end = latest
    request.hard_constraints.latest_arrival_time = latest

    response = plan_trip(request, _context())

    assert response.planning_status == PlanningStatus.NO_MATCH
    assert response.plans == []
    assert response.recommendation_result is None
    assert response.constraint_analysis is not None
    assert response.constraint_analysis.alternatives
    assert response.constraint_analysis.alternatives[0].violations[0].deviation.kind == "DURATION"
    assert response.constraint_analysis.alternatives[0].plan.recommendation_eligibility == RecommendationEligibility.NOT_RECOMMENDED


def test_feature_flag_restores_legacy_failed_no_match_behavior(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRAVEL_CONSTRAINT_ANALYSIS_ENABLED", "false")
    request = _request()
    request.hard_constraints.max_total_cost = money(1)

    response = plan_trip(request, _context())

    assert response.planning_status == PlanningStatus.FAILED
    assert response.constraint_analysis is None
    assert response.plans == []


def test_blocked_plan_never_enters_relaxation_alternatives():
    request = _request()
    request.hard_constraints.allowed_transport_modes = [TransportMode.BUS]
    plans, *_ = build_plans(request)
    plan = plans[0]
    blocked_risk = plan.risk_assessment.model_copy(update={"overall_risk_level": RiskLevel.BLOCKED, "recommendation_allowed": False})
    blocked = plan.model_copy(update={"risk_assessment": blocked_risk})
    evaluation = evaluate_plan_constraints(blocked, request)

    analysis = build_constraint_analysis([evaluation], [])

    assert evaluation.safe_for_relaxation is False
    assert analysis.result_type == "NO_SAFE_ALTERNATIVE"
    assert analysis.alternatives == []


def test_time_and_budget_tracks_are_not_collapsed_into_cross_unit_score():
    request = _request()
    plans, *_ = build_plans(request)
    assert len(plans) >= 2
    request.hard_constraints.max_total_cost = money(1)
    latest = TimePoint(datetime=datetime.fromisoformat("2026-05-21T09:05:00+08:00"), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")
    request.latest_arrival_time = latest
    request.hard_constraints.latest_arrival_time = latest
    pool = generate_candidate_plan_pool(plans, request)

    analysis = build_constraint_analysis(pool.constraint_evaluations, [])

    categories = {item.category for item in analysis.alternatives}
    assert "CLOSEST_TO_TIME" in categories
    assert any(violation.constraint_type == "MAX_TOTAL_COST" for item in analysis.alternatives for violation in item.violations)
    assert len(analysis.alternatives) <= 3
