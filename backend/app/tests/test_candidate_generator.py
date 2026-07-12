from app.core.context import RequestContext
from app.models.schemas import RecommendationType, TransportMode, money
from app.services.candidate_generator import generate_candidate_plan_pool
from app.services.constraints.relaxation_selector import build_constraint_analysis
from app.services.intent_parser import parse_travel_request
from app.services.planner import build_plans


def _request():
    ctx = RequestContext("req_candidates", "trace_candidates", "corr_candidates", "idem_candidates")
    return parse_travel_request(
        "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。",
        ctx,
    )


def test_candidate_pool_filters_disallowed_transport_modes_with_explanations():
    request = _request()
    request.hard_constraints.allowed_transport_modes = [TransportMode.BUS]
    plans, *_ = build_plans(request)

    result = generate_candidate_plan_pool(plans, request)
    candidate_ids = {plan.plan_id for plan in result.llm_candidate_plans}

    assert candidate_ids == set()
    assert any(item.reason_code == "TRANSPORT_MODE_NOT_ALLOWED" for item in result.missing_plan_explanations)
    analysis = build_constraint_analysis(result.constraint_evaluations, [])
    assert analysis.result_type == "RELAXATION_AVAILABLE"
    assert all(item.plan.can_be_selected_by_llm is False for item in analysis.alternatives)
    assert all(item.plan.booking_redirects == [] for item in analysis.alternatives)
    assert len(result.llm_candidate_plans) <= 15


def test_candidate_pool_applies_budget_and_low_cost_sorting():
    request = _request()
    request.preferences = [RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED]
    request.soft_preferences.prefer_low_cost = True
    request.hard_constraints.max_total_cost = money(1000)
    plans, *_ = build_plans(request)

    result = generate_candidate_plan_pool(plans, request)
    costs = [plan.cost_breakdown.total_cost.amount_minor for plan in result.llm_candidate_plans]

    assert costs == sorted(costs)
    assert all(cost <= 1000 for cost in costs)
    assert any(item.reason_code == "BUDGET_CONSTRAINT_EXCEEDED" for item in result.missing_plan_explanations)
    analysis = build_constraint_analysis(result.constraint_evaluations, [])
    assert len(analysis.alternatives) <= 3
    assert any(item.category == "CLOSEST_TO_BUDGET" for item in analysis.alternatives)
