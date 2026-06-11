from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import LLMRecommendationOutput, RecommendationSlot, RecommendationSlotStatus, RecommendationType

client = TestClient(app)

RAW_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。"
BEIJING_GUANGZHOU_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从北京到广州，帮我找最舒服的方式。"


def test_health_and_data_source_status():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["schema_version"] == "1.15"

    status = client.get("/api/data-sources/status")
    assert status.status_code == 200
    body = status.json()
    assert body["schema_version"] == "1.15"
    source_ids = {source["source_id"] for source in body["sources"]}
    assert {"amap_route", "baidu_map_route", "amadeus_flight_offers", "rail_authorized_partner", "real_llm", "internal_calc"}.issubset(source_ids)
    assert not any(source_id.startswith("simulated_") for source_id in source_ids)
    assert "source_id" in body["sources"][0]
    assert "qps_limit" not in body["sources"][0]


def test_parse_travel_request():
    response = client.post("/api/travel/parse", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "上海嘉定南翔格林公馆"
    assert body["travel_request"]["destination_text"] == "青岛金水假日酒店"
    assert body["travel_request"]["preferences"][:2] == ["MOST_COMFORTABLE", "CHEAPEST"]


def test_parse_preference_synonyms_and_text_order():
    cases = [
        ("帮我找最舒服的方式", "MOST_COMFORTABLE"),
        ("帮我找最舒适的方式", "MOST_COMFORTABLE"),
        ("帮我找最便宜的方式", "CHEAPEST"),
        ("帮我找最优惠的方式", "CHEAPEST"),
        ("帮我找省钱的方式", "CHEAPEST"),
    ]
    for suffix, expected in cases:
        raw = f"我 2026 年 5 月 21 日上午 9 点后，从上海到青岛，{suffix}。"
        response = client.post("/api/travel/parse", json={"raw_user_input": raw})
        assert response.status_code == 200
        request = response.json()["travel_request"]
        assert request["preference_source"] == "USER_EXPLICIT"
        assert request["preferences"][0] == expected

    comfort_first = client.post(
        "/api/travel/parse",
        json={"raw_user_input": RAW_INPUT},
    )
    cheapest_first = client.post(
        "/api/travel/parse",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最便宜和最舒服的方式。"},
    )
    assert comfort_first.json()["travel_request"]["preferences"][:2] == ["MOST_COMFORTABLE", "CHEAPEST"]
    assert cheapest_first.json()["travel_request"]["preferences"][:2] == ["CHEAPEST", "MOST_COMFORTABLE"]


def test_parse_transport_constraints():
    raw = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，不坐飞机，只看高铁，不接受高铁中转。"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert "FLIGHT" in request["hard_constraints"]["excluded_transport_modes"]
    assert "RAIL" in request["hard_constraints"]["allowed_transport_modes"]
    assert request["soft_preferences"]["accept_rail_transfer"] is False


def test_parse_returns_error_for_missing_date_and_ambiguous_place():
    missing_date = client.post("/api/travel/parse", json={"raw_user_input": "从上海到青岛，帮我找最舒服的方式。"})
    ambiguous_place = client.post("/api/travel/parse", json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从家里到酒店。"})
    assert missing_date.status_code == 400
    assert ambiguous_place.status_code == 400
    assert missing_date.json()["error_code"] == "HTTP_400"
    assert ambiguous_place.json()["error_code"] == "HTTP_400"


def test_plan_without_llm_returns_partial_without_generated_recommendation_cards():
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "PARTIAL"
    assert body["destination_presentation"]["destination_key"] == "qingdao"
    assert body["recommendation_result"] is None
    assert "recommendation_result" in body["missing_components"]
    assert any(failure["source_id"] == "real_llm" and failure["fallback_used"] is False for failure in body["source_failures"])
    assert any("未使用确定性规则生成" in warning for warning in body["user_visible_warnings"])
    assert body["source_failures"]
    assert "TRANSFER_RAIL" in body["blocked_plan_types"]


def test_plan_uses_real_llm_recommendations_when_provider_returns_valid_output(monkeypatch):
    class _ValidLLMProvider:
        source_id = "real_llm"

        def recommend(self, llm_input):
            plan_ids = llm_input.candidate_plan_ids[:3]
            return LLMRecommendationOutput(
                selected_recommendations=[
                    RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[0], reason="LLM selected cheapest from candidates."),
                    RecommendationSlot(recommendation_type=RecommendationType.MOST_COMFORTABLE, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[1], reason="LLM selected comfort from candidates."),
                    RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[2], reason="LLM selected balanced from candidates."),
                ],
                validation_blockers=[],
                explanation="valid",
            )

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _ValidLLMProvider())
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "COMPLETE"
    assert len(body["recommendation_result"]["recommendations"]) == 3
    selected = {slot["plan_id"] for slot in body["recommendation_result"]["recommendations"] if slot["plan_id"]}
    assert "plan_blocked_shqd" not in selected
    assert "plan_ticket_a_shqd" not in selected
    assert "plan_buy_short_shqd" not in selected


def test_ticket_enhancement_rules_are_visible_but_filtered():
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    plans = {plan["plan_id"]: plan for plan in response.json()["plans"]}
    assert plans["plan_ticket_s_shqd"]["recommendation_eligibility"] == "ELIGIBLE"
    assert plans["plan_ticket_s_shqd"]["ticket_enhancement"]["grade"] == "S"
    assert plans["plan_ticket_s_shqd"]["can_be_selected_by_llm"] is True

    assert plans["plan_ticket_a_shqd"]["recommendation_eligibility"] == "NOT_RECOMMENDED"
    assert plans["plan_ticket_a_shqd"]["ticket_enhancement"]["grade"] == "A"
    assert plans["plan_ticket_a_shqd"]["can_be_selected_by_llm"] is False

    assert plans["plan_buy_short_shqd"]["ticket_enhancement"]["requires_onboard_supplement"] is True
    assert plans["plan_buy_short_shqd"]["risk_assessment"]["overall_risk_level"] == "HIGH"
    assert plans["plan_buy_short_shqd"]["can_be_selected_by_llm"] is False


def test_recalculate_rail_seat_updates_cost_comfort_and_stored_snapshot():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = next(item for item in plan_response["plans"] if item["plan_id"] == "plan_rail_direct_shqd")
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
    before_total = plan["cost_breakdown"]["total_cost"]["amount_minor"]
    before_duration = plan["total_duration_minutes"]
    before_comfort = plan["comfort_score"]["total_score"]
    recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.15",
            "request_id": "req_test",
            "idempotency_key": "idem_test",
            "plan_id": plan["plan_id"],
            "change_type": "RAIL_SEAT",
            "target_segment_id": rail_segment["segment_id"],
            "selected_option": {
                "option_type": "RAIL_SEAT",
                "option_id": "seat_first",
                "option_value": "一等座",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert recalc.status_code == 200
    body = recalc.json()
    updated_plan = body["plan"]
    updated_rail_segment = next(seg for seg in updated_plan["segments"] if seg["segment_id"] == rail_segment["segment_id"])
    assert body["change_summary"]["cost_delta"]["amount_minor"] == 22000
    assert body["change_summary"]["duration_delta_minutes"] == 0
    assert updated_plan["cost_breakdown"]["total_cost"]["amount_minor"] == before_total + 22000
    assert updated_plan["total_duration_minutes"] == before_duration
    assert updated_plan["comfort_score"]["total_score"] > before_comfort
    assert updated_rail_segment["selected_seat_option_id"] == "seat_first"
    assert any("一等座" in item["label"] for item in updated_plan["cost_breakdown"]["items"])

    stored = client.get(f"/api/travel/plans/{plan['plan_id']}")
    assert stored.status_code == 200
    assert stored.json()["plan"]["cost_breakdown"]["total_cost"] == updated_plan["cost_breakdown"]["total_cost"]


def test_recalculate_flight_cabin_and_local_transfer_consistency():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    flight_plan = next(item for item in plan_response["plans"] if item["plan_id"] == "plan_flight_direct_shqd")
    flight_segment = next(seg for seg in flight_plan["segments"] if seg["segment_type"] == "FLIGHT")
    flight_before_total = flight_plan["cost_breakdown"]["total_cost"]["amount_minor"]
    flight_before_duration = flight_plan["total_duration_minutes"]

    cabin_recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.15",
            "request_id": "req_cabin",
            "idempotency_key": "idem_cabin",
            "plan_id": flight_plan["plan_id"],
            "change_type": "FLIGHT_CABIN",
            "target_segment_id": flight_segment["segment_id"],
            "selected_option": {
                "option_type": "FLIGHT_CABIN",
                "option_id": "cabin_premium",
                "option_value": "超级经济舱",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert cabin_recalc.status_code == 200
    cabin_plan = cabin_recalc.json()["plan"]
    cabin_segment = next(seg for seg in cabin_plan["segments"] if seg["segment_id"] == flight_segment["segment_id"])
    assert cabin_recalc.json()["change_summary"]["cost_delta"]["amount_minor"] == 26000
    assert cabin_plan["cost_breakdown"]["total_cost"]["amount_minor"] == flight_before_total + 26000
    assert cabin_plan["total_duration_minutes"] == flight_before_duration
    assert cabin_segment["selected_cabin_option_id"] == "cabin_premium"

    transfer_segment = next(seg for seg in cabin_plan["segments"] if seg["segment_type"] == "LOCAL_TRANSFER")
    transfer_before_total = cabin_plan["cost_breakdown"]["total_cost"]["amount_minor"]
    transfer_before_duration = cabin_plan["total_duration_minutes"]
    subway_option = next(option for option in transfer_segment["transfer_options"] if option["option_id"] == "transfer_subway")

    transfer_recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.15",
            "request_id": "req_transfer",
            "idempotency_key": "idem_transfer",
            "plan_id": cabin_plan["plan_id"],
            "change_type": "LOCAL_TRANSFER",
            "target_segment_id": transfer_segment["segment_id"],
            "selected_option": {
                "option_type": "LOCAL_TRANSFER",
                "option_id": "transfer_subway",
                "option_value": "地铁",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert transfer_recalc.status_code == 200
    transfer_body = transfer_recalc.json()
    transfer_plan = transfer_body["plan"]
    updated_transfer = next(seg for seg in transfer_plan["segments"] if seg["segment_id"] == transfer_segment["segment_id"])
    expected_cost_delta = subway_option["estimated_cost"]["amount_minor"] - transfer_segment["estimated_cost"]["amount_minor"]
    expected_duration_delta = subway_option["duration_minutes"] - transfer_segment["duration_minutes"]
    assert transfer_body["change_summary"]["cost_delta"]["amount_minor"] == expected_cost_delta
    assert transfer_body["change_summary"]["duration_delta_minutes"] == expected_duration_delta
    assert transfer_plan["cost_breakdown"]["total_cost"]["amount_minor"] == transfer_before_total + expected_cost_delta
    assert transfer_plan["total_duration_minutes"] == transfer_before_duration + expected_duration_delta
    assert updated_transfer["option_id"] == "transfer_subway"
    assert updated_transfer["transfer_mode"] == "SUBWAY"


def test_booking_redirect():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = next(item for item in plan_response["plans"] if item["plan_id"] == "plan_rail_direct_shqd")
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")

    redirect = client.post(
        "/api/redirect/booking",
        json={
            "schema_version": "1.15",
            "request_id": "req_test",
            "idempotency_key": "idem_redirect",
            "plan_id": plan["plan_id"],
            "segment_id": rail_segment["segment_id"],
            "redirect_type": "RAIL_12306",
        },
    )
    assert redirect.status_code == 200
    assert redirect.json()["redirect"]["transaction_boundary"] == "REDIRECT_ONLY"


def test_non_sample_route_without_llm_has_no_generated_recommendation_cards():
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从北京到广州，force_invalid_llm"},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(plan["plan_id"].endswith("_bg") for plan in body["plans"])
    assert body["planning_status"] == "PARTIAL"
    assert body["recommendation_result"] is None


def test_non_sample_route_uses_beijing_guangzhou_provider_network():
    response = client.post("/api/travel/plan", json={"raw_user_input": BEIJING_GUANGZHOU_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "北京市朝阳区国贸"
    assert body["travel_request"]["destination_text"] == "广州天河体育中心"
    assert len(body["plans"]) >= 5
    assert all(plan["plan_id"].endswith("_bg") for plan in body["plans"])

    direct_rail = next(plan for plan in body["plans"] if plan["plan_id"] == "plan_rail_direct_bg")
    rail_segment = next(segment for segment in direct_rail["segments"] if segment["segment_type"] == "RAIL")
    assert rail_segment["origin_station"] == "北京西"
    assert rail_segment["destination_station"] == "广州南"
    assert "广州南" in rail_segment["stop_sequence"]
    assert "上海虹桥" not in rail_segment["origin_station"] + rail_segment["destination_station"]
    assert "青岛北" not in rail_segment["origin_station"] + rail_segment["destination_station"]


def test_api_error_paths_return_error_response():
    response = client.get("/api/travel/plans/missing")
    assert response.status_code == 404
    assert response.json()["error_code"] == "HTTP_404"

    malformed = client.post("/api/travel/plan", json={})
    assert malformed.status_code == 422
    assert malformed.json()["error_code"] == "VALIDATION_ERROR"

    missing_recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.15",
            "request_id": "req_missing",
            "idempotency_key": "idem_missing",
            "plan_id": "missing_plan",
            "change_type": "RAIL_SEAT",
            "target_segment_id": "seg_missing",
            "selected_option": {
                "option_type": "RAIL_SEAT",
                "option_id": "seat_first",
                "option_value": "一等座",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert missing_recalc.status_code == 404
    assert missing_recalc.json()["error_code"] == "HTTP_404"

    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = next(item for item in plan_response["plans"] if item["plan_id"] == "plan_rail_direct_shqd")
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
    invalid_option = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.15",
            "request_id": "req_invalid_option",
            "idempotency_key": "idem_invalid_option",
            "plan_id": plan["plan_id"],
            "change_type": "RAIL_SEAT",
            "target_segment_id": rail_segment["segment_id"],
            "selected_option": {
                "option_type": "RAIL_SEAT",
                "option_id": "seat_missing",
                "option_value": "不存在座席",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert invalid_option.status_code == 400
    assert invalid_option.json()["schema_version"] == "1.15"
    assert invalid_option.json()["error_code"] == "HTTP_400"
