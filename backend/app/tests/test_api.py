from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

RAW_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。"


def test_health_and_data_source_status():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["schema_version"] == "1.15"

    status = client.get("/api/data-sources/status")
    assert status.status_code == 200
    body = status.json()
    assert body["schema_version"] == "1.15"
    assert body["sources"]
    assert "source_id" in body["sources"][0]
    assert "qps_limit" not in body["sources"][0]


def test_parse_travel_request():
    response = client.post("/api/travel/parse", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "上海嘉定南翔格林公馆"
    assert body["travel_request"]["destination_text"] == "青岛金水假日酒店"
    assert "CHEAPEST" in body["travel_request"]["preferences"]


def test_parse_most_comfortable_as_primary_preference():
    raw = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服的方式。"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["preference_source"] == "USER_EXPLICIT"
    assert request["preferences"][0] == "MOST_COMFORTABLE"


def test_parse_cheapest_as_primary_preference():
    raw = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最便宜的方式。"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["preference_source"] == "USER_EXPLICIT"
    assert request["preferences"][0] == "CHEAPEST"


def test_parse_conflicting_preferences_by_text_order():
    comfort_first = client.post(
        "/api/travel/parse",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。"},
    )
    cheapest_first = client.post(
        "/api/travel/parse",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最便宜和最舒服的方式。"},
    )
    assert comfort_first.status_code == 200
    assert cheapest_first.status_code == 200
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


def test_plan_recommendations_and_blocked_filter():
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "COMPLETE"
    assert len(body["recommendation_result"]["recommendations"]) == 3
    selected = {slot["plan_id"] for slot in body["recommendation_result"]["recommendations"] if slot["plan_id"]}
    assert "plan_blocked_shqd" not in selected
    assert body["source_failures"]
    assert "TRANSFER_RAIL" in body["blocked_plan_types"]


def test_recalculate_and_booking_redirect():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = next(item for item in plan_response["plans"] if item["plan_id"] == "plan_rail_direct_shqd")
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
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
                "source_option_version": "mock_v1",
            },
            "recalculate_scope": "PLAN_TOTAL",
        },
    )
    assert recalc.status_code == 200
    assert recalc.json()["change_summary"]["cost_delta"]["amount_minor"] > 0

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


def test_non_sample_route_and_llm_fallback():
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从北京到广州，force_invalid_llm"},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(plan["plan_id"].endswith("_bg") for plan in body["plans"])
    assert body["recommendation_result"]["llm_validation_result"]["final_strategy"] == "DETERMINISTIC_FALLBACK"


def test_error_response_for_missing_plan():
    response = client.get("/api/travel/plans/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["schema_version"] == "1.15"
    assert body["error_code"] == "HTTP_404"
