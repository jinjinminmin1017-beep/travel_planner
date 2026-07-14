from fastapi.testclient import TestClient

from app.main import app
from app.data_sources.flight_providers import FlightProviderSearchResult
from app.data_sources.map_providers import AmapRouteProvider, MapRouteProviderResult
from app.data_sources.rail_providers import RailProviderSearchResult
from app.models.schemas import LLMRecommendationOutput, RecommendationSlot, RecommendationSlotStatus, RecommendationType
from app.core import security
from app.services import store

client = TestClient(app)

RAW_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。"
BEIJING_GUANGZHOU_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从北京到广州，帮我找最舒服的方式。"


def _first_dynamic_rail_plan(plans):
    return next(item for item in plans if item["plan_id"].startswith("plan_rail_direct_dynamic"))


def _assert_no_legacy_runtime_plans(plans):
    plan_ids = {item["plan_id"] for item in plans}
    assert not any(plan_id.endswith("_shqd") or plan_id.endswith("_bg") for plan_id in plan_ids)
    assert not any("ticket" in plan_id or "buy_short" in plan_id or "blocked" in plan_id for plan_id in plan_ids)


def test_health_and_data_source_status():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["schema_version"] == "1.17"

    status = client.get("/api/data-sources/status")
    assert status.status_code == 200
    body = status.json()
    assert body["schema_version"] == "1.17"
    source_ids = {source["source_id"] for source in body["sources"]}
    assert {"amap_route", "baidu_map_route", "airline_mu_public_query", "rail_12306_public_query", "real_llm", "internal_calc"}.issubset(source_ids)
    assert not any(source_id.startswith("simulated_") for source_id in source_ids)
    assert "source_id" in body["sources"][0]
    assert "qps_limit" not in body["sources"][0]

    admin_status = client.get("/api/admin/data-sources")
    assert admin_status.status_code == 200
    admin_body = admin_status.json()
    assert admin_body["sources"]
    assert "qps_limit" not in admin_body["sources"][0]


def test_observability_metrics_are_read_only_and_aggregate_requests():
    client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    response = client.get("/api/observability/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["counters"]["travel_requests"] >= 1
    assert "generated_at" in body
    assert isinstance(body["provider_failures"], dict)


def test_security_middleware_adds_device_id_and_enforces_limits(monkeypatch):
    security._RATE_WINDOWS.clear()
    health = client.get("/api/health", headers={"x-device-id": "device_test"})
    assert health.status_code == 200
    assert health.headers["x-device-id"] == "device_test"

    monkeypatch.setenv("TRAVEL_API_RATE_LIMIT_PER_MINUTE", "1")
    security._RATE_WINDOWS.clear()
    assert client.get("/api/health", headers={"x-device-id": "device_limited"}).status_code == 200
    limited = client.get("/api/health", headers={"x-device-id": "device_limited"})
    assert limited.status_code == 429
    assert limited.json()["error_code"] == "RATE_LIMITED"

    monkeypatch.setenv("TRAVEL_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("TRAVEL_API_KEY", "secret")
    security._RATE_WINDOWS.clear()
    unauthorized = client.get("/api/health", headers={"x-device-id": "device_key"})
    assert unauthorized.status_code == 401
    authorized = client.get("/api/health", headers={"x-device-id": "device_key_ok", "x-api-key": "secret"})
    assert authorized.status_code == 200


def test_parse_travel_request():
    response = client.post("/api/travel/parse", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "上海嘉定南翔格林公馆"
    assert body["travel_request"]["destination_text"] == "青岛金水假日酒店"
    assert body["travel_request"]["preferences"][:2] == ["MOST_COMFORTABLE", "CHEAPEST"]
    assert body["llm_validation_result"]["final_strategy"] == "FALLBACK_RULES"
    assert body["llm_validation_result"]["prompt_version"] == "intent_parser_prompt_v1.0"


def test_parse_english_or_mixed_input():
    response = client.post("/api/travel/parse", json={"raw_user_input": "2026-05-21 from Beijing to Guangzhou, comfortable, train only"})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "北京市朝阳区国贸"
    assert body["travel_request"]["destination_text"] == "广州天河体育中心"
    assert body["travel_request"]["preferences"][0] == "MOST_COMFORTABLE"
    assert body["travel_request"]["hard_constraints"]["allowed_transport_modes"] == ["RAIL"]


def test_parse_explicit_poi_route_input():
    response = client.post("/api/travel/parse", json={"raw_user_input": "从上海东方明珠塔出发，到北京天安门，6月15号下午"})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["origin_text"] == "上海东方明珠塔"
    assert request["destination_text"] == "北京天安门"
    assert request["travel_date"] == "2027-06-15"


def test_parse_chinese_dot_date_with_explicit_year():
    response = client.post("/api/travel/parse", json={"raw_user_input": "我要从上海东方明珠塔到北京天安门，2026年6.24号早上"})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["origin_text"] == "上海东方明珠塔"
    assert request["destination_text"] == "北京天安门"
    assert request["travel_date"] == "2026-06-24"


def test_parse_date_prefix_with_explicit_from_to_route():
    response = client.post("/api/travel/parse", json={"raw_user_input": "6.26上午，从上海东方明珠塔到云南洱海"})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["origin_text"] == "上海东方明珠塔"
    assert request["destination_text"] == "云南洱海"
    assert request["travel_date"] == "2027-06-26"


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


def test_parse_budget_time_and_passenger_notes():
    raw = "我 2026 年 5 月 21 日上午 9 点后，从上海到青岛，预算不要超过1000，晚上8点前到，带老人和行李多。"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["time_anchor_type"] == "ARRIVAL"
    assert request["hard_constraints"]["max_total_cost"]["amount_minor"] == 100000
    assert request["latest_arrival_time"]["datetime"].startswith("2026-05-21T20:00:00")
    assert "老人" in request["soft_preferences"]["passenger_notes"]
    assert "行李多" in request["soft_preferences"]["passenger_notes"]


def test_parse_period_departure_window():
    raw = "我要从上海东方明珠塔到北京天安门，2026年6.24号早上出发"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 200
    request = response.json()["travel_request"]
    assert request["time_anchor_type"] == "DEPARTURE"
    assert request["time_window_start"]["datetime"].startswith("2026-06-24T06:00:00")
    assert request["time_window_end"]["datetime"].startswith("2026-06-24T11:00:00")
    assert request["earliest_departure_time"]["datetime"].startswith("2026-06-24T06:00:00")


def test_parse_returns_error_for_missing_date_and_ambiguous_place():
    missing_date = client.post("/api/travel/parse", json={"raw_user_input": "从上海到青岛，帮我找最舒服的方式。"})
    ambiguous_place = client.post("/api/travel/parse", json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从家里到酒店。"})
    assert missing_date.status_code == 400
    assert ambiguous_place.status_code == 400
    assert missing_date.json()["error_code"] == "PARSE_NEEDS_INPUT"
    assert ambiguous_place.json()["error_code"] == "PARSE_NEEDS_INPUT"
    assert "travel_date" in missing_date.json()["details"]["missing_fields"]
    assert missing_date.json()["details"]["follow_up_questions"]
    assert {"origin_text", "destination_text"}.issubset(set(ambiguous_place.json()["details"]["missing_fields"]))


def test_parse_returns_follow_up_for_conflicting_transport_constraints():
    raw = "我 2026 年 5 月 21 日上午 9 点后，从上海到青岛，只看高铁，但又不坐高铁。"
    response = client.post("/api/travel/parse", json={"raw_user_input": raw})
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "PARSE_NEEDS_INPUT"
    assert "hard_constraints" in body["details"]["missing_fields"]
    assert "交通方式限制" in body["user_visible_message"]


def test_parse_uses_llm_repair_once_when_enabled_provider_returns_invalid_output(monkeypatch):
    class _RepairingIntentProvider:
        source_id = "real_llm"
        model_name = "test-intent-model"

        def parse_intent(self, raw_user_input, request_id, current_date, default_timezone):
            return '{"schema_version":"1.17","origin_text":"","destination_text":"青岛金水假日酒店"}'

        def repair_intent(self, raw_llm_output, invalid_reasons, raw_user_input, request_id):
            return (
                "{"
                '"schema_version":"1.17",'
                f'"request_id":"{request_id}",'
                f'"raw_user_input":"{raw_user_input}",'
                '"origin_text":"上海嘉定南翔格林公馆",'
                '"destination_text":"青岛金水假日酒店",'
                '"travel_date":"2026-05-21",'
                '"preferences":["CHEAPEST","MOST_COMFORTABLE","BALANCED"],'
                '"preference_source":"SYSTEM_DEFAULT",'
                '"hard_constraints":{"allowed_transport_modes":[],"excluded_transport_modes":[]},'
                '"soft_preferences":{}'
                "}"
            )

    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", lambda: _RepairingIntentProvider())
    response = client.post("/api/travel/parse", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "上海嘉定南翔格林公馆"
    assert body["llm_validation_result"]["repair_attempted"] is True
    assert body["llm_validation_result"]["repair_success"] is True
    assert body["llm_validation_result"]["final_strategy"] == "REPAIRED"
    assert body["llm_validation_result"]["model_name"] == "test-intent-model"


def test_parse_falls_back_to_rules_when_llm_output_and_repair_fail(monkeypatch):
    class _InvalidIntentProvider:
        source_id = "real_llm"
        model_name = "test-invalid-intent-model"

        def parse_intent(self, raw_user_input, request_id, current_date, default_timezone):
            return '{"origin":"上海东方明珠塔","destination":"北京天安门","departure_date":"2026-06-24"}'

        def repair_intent(self, raw_llm_output, invalid_reasons, raw_user_input, request_id):
            raise ValueError("repair timed out")

    monkeypatch.setattr("app.services.intent_parser.build_enabled_intent_llm_provider", lambda: _InvalidIntentProvider())
    response = client.post("/api/travel/parse", json={"raw_user_input": "我要从上海东方明珠塔到北京天安门，2026年6.24号早上"})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["travel_date"] == "2026-06-24"
    assert body["travel_request"]["origin_text"] == "上海东方明珠塔"
    assert body["travel_request"]["destination_text"] == "北京天安门"
    assert body["llm_validation_result"]["final_strategy"] == "FALLBACK_RULES"


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
    for failure in body["source_failures"]:
        assert failure["request_id"]
        assert failure["trace_id"]
        assert failure["correlation_id"]
        assert "source_used_id" in failure
        assert "fallback_reason" in failure


def test_plan_has_door_to_door_segment_times():
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    plan = _first_dynamic_rail_plan(body["plans"])
    first_transfer = plan["segments"][0]
    rail_segment = next(segment for segment in plan["segments"] if segment["segment_type"] == "RAIL")
    last_transfer = plan["segments"][-1]
    assert first_transfer["departure_time"]["datetime"]
    assert first_transfer["arrival_time"]["datetime"] < rail_segment["departure_time"]["datetime"]
    assert plan["departure_time"] == first_transfer["departure_time"]
    assert last_transfer["arrival_time"] == plan["arrival_time"]


def test_plan_requeries_and_filters_by_arrival_time_constraint():
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "我 2026 年 5 月 21 日，从上海到青岛，只看高铁，不坐飞机，中午12点前到。"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "NO_MATCH"
    assert body["plans"] == []
    assert body["recommendation_result"] is None
    assert body["constraint_analysis"]["alternatives"]
    assert any(item["reason_code"] == "TIME_CONSTRAINT_TOO_LATE" for item in body["missing_plan_explanations"])


def test_async_plan_returns_running_job_then_pollable_result():
    response = client.post("/api/travel/plan/async", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "RUNNING"
    assert body["progress"] == 15
    assert body["plans"] == []
    assert body["async_job"]["job_status"] == "RUNNING"
    assert body["async_job"]["polling_url"].startswith("/api/travel/jobs/")

    poll = client.get(body["async_job"]["polling_url"])
    assert poll.status_code == 200
    poll_body = poll.json()
    assert poll_body["planning_status"] in {"PARTIAL", "COMPLETE", "NO_MATCH", "FAILED"}
    assert poll_body["progress"] == 100
    assert poll_body["async_job"]["job_status"] in {"PARTIAL_READY", "COMPLETE", "FAILED"}
    if poll_body["planning_status"] not in {"FAILED", "NO_MATCH"}:
        assert poll_body["plans"]


def test_async_plan_survives_amap_transit_empty_cost(monkeypatch):
    class _AmapResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _AmapClient:
        def get(self, url, params):
            if url.endswith("/v3/direction/transit/integrated"):
                return _AmapResponse(
                    {
                        "status": "1",
                        "route": {
                            "transits": [
                                {
                                    "distance": "8600",
                                    "duration": "2400",
                                    "walking_distance": "650",
                                    "cost": [],
                                }
                            ]
                        },
                    }
                )
            if url.endswith("/v3/direction/walking"):
                return _AmapResponse(
                    {"status": "1", "route": {"paths": [{"distance": "900", "duration": "660"}]}}
                )
            return _AmapResponse(
                {
                    "status": "1",
                    "route": {
                        "taxi_cost": "18.50",
                        "paths": [{"distance": "6200", "duration": "1200"}],
                    },
                }
            )

    provider = AmapRouteProvider("test-key", client=_AmapClient(), base_url="https://example.test")

    def amap_estimate(request, environment=None):
        return MapRouteProviderResult(estimate=provider.estimate_route(request), attempted_source_ids=["amap_route"])

    monkeypatch.setattr("app.services.planner.estimate_route_with_enabled_provider_result", amap_estimate)

    response = client.post(
        "/api/travel/plan/async",
        json={"raw_user_input": RAW_INPUT},
        headers={"idempotency-key": "idem_async_amap_empty_transit_cost"},
    )
    poll = client.get(response.json()["async_job"]["polling_url"])
    body = poll.json()

    assert response.status_code == 200
    assert poll.status_code == 200
    assert body["planning_status"] in {"COMPLETE", "PARTIAL", "NO_MATCH"}
    assert body["async_job"]["job_status"] in {"COMPLETE", "PARTIAL_READY"}
    assert body["planning_status"] != "FAILED"
    assert body["async_job"]["job_status"] != "FAILED"


def test_async_no_match_is_a_completed_business_job():
    response = client.post(
        "/api/travel/plan/async",
        json={"raw_user_input": "我 2026 年 5 月 21 日，从上海到青岛，只看高铁，不坐飞机，中午12点前到。"},
        headers={"idempotency-key": "idem_async_no_match_v116"},
    )
    assert response.status_code == 200
    poll = client.get(response.json()["async_job"]["polling_url"])
    body = poll.json()
    assert body["planning_status"] == "NO_MATCH"
    assert body["async_job"]["job_status"] == "COMPLETE"
    assert body["plans"] == []
    assert body["constraint_analysis"] is not None


def test_async_plan_accepts_naive_datetime_with_declared_timezone():
    parsed = client.post("/api/travel/parse", json={"raw_user_input": RAW_INPUT}).json()["travel_request"]
    naive_latest = {
        "datetime": "2026-05-21T17:00:00",
        "timezone": "Asia/Shanghai",
        "source_timezone": "Asia/Shanghai",
    }
    parsed["time_anchor_type"] = "ARRIVAL"
    parsed["latest_arrival_time"] = naive_latest
    parsed["time_window_end"] = naive_latest
    parsed["hard_constraints"]["latest_arrival_time"] = naive_latest

    response = client.post(
        "/api/travel/plan/async",
        json={"travel_request": parsed},
        headers={"x-idempotency-key": "idem_async_naive_timezone_regression"},
    )
    poll = client.get(response.json()["async_job"]["polling_url"])
    body = poll.json()

    assert response.status_code == 200
    assert poll.status_code == 200
    assert body["planning_status"] in {"COMPLETE", "PARTIAL", "NO_MATCH"}
    assert body["async_job"]["job_status"] in {"COMPLETE", "PARTIAL_READY"}
    assert body["travel_request"]["latest_arrival_time"]["datetime"].endswith("+08:00")


def test_async_background_error_is_logged_and_not_exposed(monkeypatch, caplog):
    secret_error = "can't compare offset-naive and offset-aware datetimes"

    def fail_planning(*args, **kwargs):
        raise TypeError(secret_error)

    monkeypatch.setattr("app.main.plan_trip", fail_planning)
    caplog.set_level("ERROR", logger="app.api")
    response = client.post(
        "/api/travel/plan/async",
        json={"raw_user_input": RAW_INPUT},
        headers={
            "x-request-id": "req_background_failure",
            "x-trace-id": "trace_background_failure",
            "x-correlation-id": "corr_background_failure",
            "x-idempotency-key": "idem_background_failure",
        },
    )
    poll = client.get(response.json()["async_job"]["polling_url"])
    body = poll.json()

    assert body["planning_status"] == "FAILED"
    assert body["async_job"]["job_status"] == "FAILED"
    assert body["user_visible_warnings"] == ["规划任务暂时失败，请稍后重试。"]
    assert secret_error not in " ".join(body["user_visible_warnings"])
    assert "planning_job_error" in caplog.text
    assert body["async_job"]["job_id"] in caplog.text
    assert "req_background_failure" in caplog.text
    assert "trace_background_failure" in caplog.text
    assert "corr_background_failure" in caplog.text


def test_async_plan_job_retry_starts_new_pollable_job():
    response = client.post("/api/travel/plan/async", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    original_job_id = response.json()["async_job"]["job_id"]

    retry = client.post(f"/api/travel/jobs/{original_job_id}/retry")
    assert retry.status_code == 200
    retry_body = retry.json()
    assert retry_body["planning_status"] == "RUNNING"
    assert retry_body["async_job"]["job_id"] != original_job_id

    poll = client.get(retry_body["async_job"]["polling_url"])
    assert poll.status_code == 200
    assert poll.json()["planning_status"] in {"PARTIAL", "COMPLETE", "FAILED"}


def test_async_plan_uses_idempotency_key_to_reuse_job():
    headers = {"x-idempotency-key": "idem_async_same_job"}
    first = client.post("/api/travel/plan/async", json={"raw_user_input": RAW_INPUT}, headers=headers)
    second = client.post("/api/travel/plan/async", json={"raw_user_input": RAW_INPUT}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["async_job"]["job_id"] == second.json()["async_job"]["job_id"]


def test_feedback_submission_is_traceable_and_rejects_sensitive_message():
    payload = {
        "schema_version": "1.17",
        "request_id": "req_feedback",
        "trace_id": "trace_feedback",
        "correlation_id": "corr_feedback",
        "plan_id": "plan_feedback",
        "source_id": "real_llm",
        "category": "HARD_TO_UNDERSTAND",
        "message": "看不懂为什么推荐这个方案",
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["feedback_id"].startswith("fb_")
    assert body["request_id"] == "req_feedback"
    assert body["trace_id"] == "trace_feedback"
    assert body["plan_id"] == "plan_feedback"
    assert body["source_id"] == "real_llm"
    assert body["category_count"] >= 1

    blocked = client.post("/api/feedback", json={**payload, "message": "我的账号和密码是 test"})
    assert blocked.status_code == 400
    assert "不能包含" in blocked.json()["user_visible_message"]


def test_app_event_submission_updates_metrics_and_rejects_sensitive_metadata():
    payload = {
        "schema_version": "1.17",
        "event_type": "INPUT_SUBMITTED",
        "request_id": "req_event",
        "trace_id": "trace_event",
        "plan_id": None,
        "metadata": {"input_length": 20},
    }
    response = client.post("/api/events", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    metrics = client.get("/api/observability/metrics").json()
    assert metrics["app_events"]["INPUT_SUBMITTED"] >= 1
    assert any(link["request_id"] == "req_event" and link["metadata_keys"] == ["input_length"] for link in metrics["app_event_links"])

    blocked = client.post("/api/events", json={**payload, "metadata": {"token": "secret"}})
    assert blocked.status_code == 400


def test_growth_retention_events_are_counted_without_sensitive_payloads():
    for event_type in ["RECENT_PLAN_VIEWED", "FAVORITE_TOGGLED", "TRIP_REMINDER_TOGGLED", "PRICE_STATUS_WATCH_TOGGLED", "PREFERENCE_UPDATED"]:
        response = client.post(
            "/api/events",
            json={
                "schema_version": "1.17",
                "event_type": event_type,
                "request_id": "req_growth",
                "trace_id": "trace_growth",
                "plan_id": "plan_growth",
                "metadata": {"enabled": True},
            },
        )
        assert response.status_code == 200
        assert response.json()["accepted"] is True

    metrics = client.get("/api/observability/metrics").json()
    assert metrics["app_events"]["FAVORITE_TOGGLED"] >= 1
    assert any(link["event_type"] == "PRICE_STATUS_WATCH_TOGGLED" and link["request_id"] == "req_growth" for link in metrics["app_event_links"])

    blocked = client.post(
        "/api/events",
        json={
            "schema_version": "1.17",
            "event_type": "PREFERENCE_UPDATED",
            "request_id": "req_growth",
            "trace_id": "trace_growth",
            "plan_id": None,
            "metadata": {"account": "hidden@example.com"},
        },
    )
    assert blocked.status_code == 400


def test_plan_snapshot_survives_memory_index_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAVEL_SQLITE_PATH", str(tmp_path / "planner.sqlite3"))
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    plan_id = response.json()["plans"][0]["plan_id"]

    store.PLANS.clear()
    store.PLAN_RESPONSES.clear()

    stored = client.get(f"/api/travel/plans/{plan_id}")
    assert stored.status_code == 200
    assert stored.json()["plan"]["plan_id"] == plan_id


def test_plan_degrades_when_map_provider_returns_empty_result(monkeypatch):
    monkeypatch.setattr(
        "app.services.planner.estimate_route_with_enabled_provider_result",
        lambda request, environment=None: MapRouteProviderResult(
            estimate=None,
            attempted_source_ids=["amap_route"],
            failure_message="amap_route: empty route result",
        ),
    )
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "FAILED"
    assert body["plans"] == []
    assert "map_route" in body["missing_components"]
    assert any(failure["error_code"] == "MAP_TRANSFER_UNAVAILABLE" and failure["fallback_used"] is False for failure in body["source_failures"])
    assert any("无法形成完整门到门方案" in warning for warning in body["user_visible_warnings"])


def test_plan_returns_failed_business_response_when_core_providers_return_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.planner.search_rail_offers_with_enabled_provider_result",
        lambda request, environment=None: RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_12306_public_query"],
            failure_message="rail empty result",
        ),
    )
    monkeypatch.setattr(
        "app.services.planner.search_flight_offers_with_enabled_provider_result",
        lambda request, environment=None: FlightProviderSearchResult(
            offers=[],
            attempted_source_ids=["airline_mu_public_query"],
            failure_message="flight empty result",
        ),
    )

    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "FAILED"
    assert body["plans"] == []
    assert body["recommendation_result"] is None
    assert "travel_plan" in body["missing_components"]
    assert "rail_core_fact" in body["missing_components"]
    assert any(failure["source_id"] == "rail_12306_public_query" for failure in body["source_failures"])


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


def test_plan_filters_hard_constraints_before_llm_recommendation(monkeypatch):
    captured_candidate_ids = []

    class _RecordingLLMProvider:
        source_id = "real_llm"

        def recommend(self, llm_input):
            captured_candidate_ids.extend(llm_input.candidate_plan_ids)
            plan_ids = llm_input.candidate_plan_ids[:3]
            return LLMRecommendationOutput(
                selected_recommendations=[
                    RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[0], reason="LLM selected cheapest from filtered candidates."),
                    RecommendationSlot(recommendation_type=RecommendationType.MOST_COMFORTABLE, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[1], reason="LLM selected comfort from filtered candidates."),
                    RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[2], reason="LLM selected balanced from filtered candidates."),
                ],
                validation_blockers=[],
                explanation="valid",
            )

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _RecordingLLMProvider())
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从上海到青岛，只看高铁，不坐飞机。"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] == "COMPLETE"
    assert captured_candidate_ids
    assert all("flight" not in plan_id and "mixed" not in plan_id for plan_id in captured_candidate_ids)
    assert any(item["reason_code"] == "DYNAMIC_PLANNER_CAPABILITY_GAP" for item in body["missing_plan_explanations"])


def test_legacy_ticket_enhancement_templates_are_not_runtime_plans():
    response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT})
    assert response.status_code == 200
    body = response.json()
    _assert_no_legacy_runtime_plans(body["plans"])
    assert any(item["plan_type"] == "RAIL_TICKET_ENHANCEMENT" for item in body["missing_plan_explanations"])

def test_recalculate_rail_seat_updates_cost_comfort_and_stored_snapshot():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
    before_total = plan["cost_breakdown"]["total_cost"]["amount_minor"]
    before_duration = plan["total_duration_minutes"]
    before_comfort = plan["comfort_score"]["total_score"]
    recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.17",
            "request_id": "req_test",
            "idempotency_key": "idem_test",
            "plan_id": plan["plan_id"],
            "change_type": "SEAT_TYPE",
            "target_segment_id": rail_segment["segment_id"],
            "selected_option": {
                "option_type": "SEAT",
                "option_id": "seat_first",
                "option_value": "一等座",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_ONLY",
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


def test_recalculate_result_set_propagates_canonical_seat_and_persists_full_snapshot(monkeypatch):
    class _ValidLLMProvider:
        source_id = "real_llm"
        model_name = "test-result-set-model"

        def recommend(self, llm_input):
            plan_ids = llm_input.candidate_plan_ids[:3]
            return LLMRecommendationOutput(
                selected_recommendations=[
                    RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[0], reason="cheapest"),
                    RecommendationSlot(recommendation_type=RecommendationType.MOST_COMFORTABLE, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[1], reason="comfort"),
                    RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[2], reason="balanced"),
                ],
                validation_blockers=[],
                explanation="valid",
            )

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _ValidLLMProvider())
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    target_plan = _first_dynamic_rail_plan(plan_response["plans"])
    target_segment = next(segment for segment in target_plan["segments"] if segment["segment_type"] == "RAIL")
    unsupported_plan = next(
        plan for plan in store.PLANS.values()
        if plan.plan_id != target_plan["plan_id"] and any(segment.segment_type == "RAIL" for segment in plan.segments)
    )
    for segment in unsupported_plan.segments:
        if segment.segment_type == "RAIL":
            segment.seat_options = [option for option in segment.seat_options if option.seat_type != "一等座"]

    recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.17",
            "request_id": "req_result_set",
            "idempotency_key": "idem_result_set",
            "plan_id": target_plan["plan_id"],
            "change_type": "SEAT_TYPE",
            "target_segment_id": target_segment["segment_id"],
            "selected_option": {
                "option_type": "SEAT",
                "option_id": "seat_first",
                "option_value": "untrusted label",
                "source_option_version": "provider_test_v1",
            },
            "application_scope": "RESULT_SET",
            "recalculate_scope": "FULL_REEVALUATION",
        },
    )

    assert recalc.status_code == 200
    body = recalc.json()
    updated = body["updated_response"]
    assert updated["travel_request"]["preferred_rail_seat"] == "一等座"
    assert updated["travel_request"]["preference_source"] == "USER_EXPLICIT"
    assert body["preference_application"]["canonical_value"] == "一等座"
    assert unsupported_plan.plan_id in body["preference_application"]["unsupported_plan_ids"]
    assert body["recommendation_result"] == updated["recommendation_result"]
    available_ids = {
        slot["plan_id"]
        for slot in updated["recommendation_result"]["recommendations"]
        if slot["status"] == "AVAILABLE"
    }
    assert unsupported_plan.plan_id not in available_ids
    for plan in updated["plans"]:
        rail_segments = [segment for segment in plan["segments"] if segment["segment_type"] == "RAIL"]
        if not rail_segments:
            continue
        if plan["plan_id"] == unsupported_plan.plan_id:
            assert plan["recommendation_eligibility"] == "NOT_RECOMMENDED"
            assert plan["block_reason_code"] == "RAIL_SEAT_UNSUPPORTED"
            continue
        for segment in rail_segments:
            selected = next(option for option in segment["seat_options"] if option["option_id"] == segment["selected_seat_option_id"])
            assert selected["seat_type"] == "一等座"
        expected_total = sum(item["amount"]["amount_minor"] for item in plan["cost_breakdown"]["items"])
        assert plan["cost_breakdown"]["total_cost"]["amount_minor"] == expected_total

    stored = client.get(f"/api/travel/plans/{target_plan['plan_id']}")
    assert stored.status_code == 200
    assert stored.json()["plan"] == body["plan"]


def test_recalculate_local_transfer_consistency_on_dynamic_rail_plan():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    transfer_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "LOCAL_TRANSFER")
    transfer_before_total = plan["cost_breakdown"]["total_cost"]["amount_minor"]
    transfer_before_duration = plan["total_duration_minutes"]
    subway_option = next(option for option in transfer_segment["transfer_options"] if option["option_id"] == "transfer_subway")
    transfer_recalc = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.17",
            "request_id": "req_transfer",
            "idempotency_key": "idem_transfer",
            "plan_id": plan["plan_id"],
            "change_type": "LOCAL_TRANSFER_MODE",
            "target_segment_id": transfer_segment["segment_id"],
            "selected_option": {
                "option_type": "TRANSFER_MODE",
                "option_id": "transfer_subway",
                "option_value": "地铁",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_ONLY",
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
    assert transfer_body["updated_response"]["planning_status"] == plan_response["planning_status"]
    assert "map_route" not in transfer_body["updated_response"]["missing_components"]

    walk_option = next((option for option in updated_transfer["transfer_options"] if option["option_id"] == "transfer_walk"), None)
    if walk_option:
        walk_recalc = client.post(
            "/api/travel/recalculate",
            json={
                "schema_version": "1.17",
                "request_id": "req_walk",
                "idempotency_key": "idem_walk",
                "plan_id": transfer_plan["plan_id"],
                "change_type": "LOCAL_TRANSFER_MODE",
                "target_segment_id": updated_transfer["segment_id"],
                "selected_option": {
                    "option_type": "TRANSFER_MODE",
                    "option_id": "transfer_walk",
                    "option_value": "步行",
                    "source_option_version": "provider_test_v1",
                },
                "recalculate_scope": "PLAN_ONLY",
            },
        )
        assert walk_recalc.status_code == 200
        walked = next(seg for seg in walk_recalc.json()["plan"]["segments"] if seg["segment_id"] == updated_transfer["segment_id"])
        assert walked["transfer_mode"] == "WALK"
        assert walked["estimated_cost"]["amount_minor"] == 0


def test_recalculate_rejects_historical_rule_estimated_transfer_options():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    stored_plan = store.PLANS[plan["plan_id"]]
    stored_transfer = next(segment for segment in stored_plan.segments if segment.segment_type == "LOCAL_TRANSFER")
    stored_transfer.transfer_options[0].route_status = "RULE_ESTIMATED"

    response = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.17",
            "request_id": "req_historical_transfer",
            "idempotency_key": "idem_historical_transfer",
            "plan_id": plan["plan_id"],
            "change_type": "LOCAL_TRANSFER_MODE",
            "target_segment_id": stored_transfer.segment_id,
            "selected_option": {
                "option_type": "TRANSFER_MODE",
                "option_id": stored_transfer.option_id,
                "option_value": stored_transfer.transfer_mode,
                "source_option_version": "historical_rule_estimated",
            },
            "recalculate_scope": "PLAN_ONLY",
        },
    )

    assert response.status_code == 400
    assert "unverifiable" in response.json()["message"]

def test_recalculate_is_idempotent_and_can_refresh_recommendation(monkeypatch):
    class _ValidLLMProvider:
        source_id = "real_llm"
        model_name = "test-recalc-model"

        def recommend(self, llm_input):
            plan_ids = llm_input.candidate_plan_ids[:3]
            return LLMRecommendationOutput(
                selected_recommendations=[
                    RecommendationSlot(recommendation_type=RecommendationType.CHEAPEST, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[0], reason="updated cheapest"),
                    RecommendationSlot(recommendation_type=RecommendationType.MOST_COMFORTABLE, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[1], reason="updated comfort"),
                    RecommendationSlot(recommendation_type=RecommendationType.BALANCED, status=RecommendationSlotStatus.AVAILABLE, plan_id=plan_ids[2], reason="updated balanced"),
                ],
                validation_blockers=[],
                explanation="valid",
            )

    monkeypatch.setattr("app.services.recommendation.build_enabled_llm_provider", lambda: _ValidLLMProvider())
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
    body = {
        "schema_version": "1.17",
        "request_id": "req_recalc_idem",
        "idempotency_key": "idem_recalc_same",
        "plan_id": plan["plan_id"],
        "change_type": "SEAT_TYPE",
        "target_segment_id": rail_segment["segment_id"],
        "selected_option": {
            "option_type": "SEAT",
            "option_id": "seat_first",
            "option_value": "一等座",
            "source_option_version": "provider_test_v1",
        },
        "recalculate_scope": "PLAN_AND_RECOMMENDATION",
    }

    first = client.post("/api/travel/recalculate", json=body)
    second = client.post("/api/travel/recalculate", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body == second_body
    assert first_body["recommendation_result"] is not None
    assert first_body["recommendation_result"]["llm_validation_result"]["model_name"] == "test-recalc-model"


def test_booking_redirect():
    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")

    redirect = client.post(
        "/api/redirect/booking",
        json={
            "schema_version": "1.17",
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
    plan_ids = [plan["plan_id"] for plan in body["plans"]]
    assert any(plan_id.startswith("plan_rail_direct_dynamic") for plan_id in plan_ids), plan_ids
    assert body["planning_status"] == "PARTIAL"
    assert body["recommendation_result"] is None


def test_non_sample_route_uses_beijing_guangzhou_provider_network():
    response = client.post("/api/travel/plan", json={"raw_user_input": BEIJING_GUANGZHOU_INPUT})
    assert response.status_code == 200
    body = response.json()
    assert body["travel_request"]["origin_text"] == "北京市朝阳区国贸"
    assert body["travel_request"]["destination_text"] == "广州天河体育中心"
    assert body["plans"]
    _assert_no_legacy_runtime_plans(body["plans"])
    assert any(plan["plan_id"].startswith("plan_rail_direct_dynamic") for plan in body["plans"])

    direct_rail = _first_dynamic_rail_plan(body["plans"])
    rail_segment = next(segment for segment in direct_rail["segments"] if segment["segment_type"] == "RAIL")
    assert rail_segment["origin_station"] == "北京西"
    assert rail_segment["destination_station"] == "广州南"
    assert "广州南" in rail_segment["stop_sequence"]
    assert "上海虹桥" not in rail_segment["origin_station"] + rail_segment["destination_station"]
    assert "青岛北" not in rail_segment["origin_station"] + rail_segment["destination_station"]
    assert any(item["reason_code"] == "DYNAMIC_PLANNER_CAPABILITY_GAP" for item in body["missing_plan_explanations"])

def test_known_city_pair_uses_dynamic_rail_provider_search():
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "我 2026 年 5 月 21 日上午 9 点后，从成都到深圳，帮我找最舒服的方式。"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planning_status"] in {"PARTIAL", "COMPLETE"}
    assert any(plan["plan_id"].startswith("plan_rail_direct_dynamic") for plan in body["plans"])
    dynamic_rail = next(plan for plan in body["plans"] if plan["plan_id"].startswith("plan_rail_direct_dynamic"))
    rail_segment = next(segment for segment in dynamic_rail["segments"] if segment["segment_type"] == "RAIL")
    assert rail_segment["origin_station"] == "成都东"
    assert rail_segment["destination_station"] == "深圳北"
    assert "route_coverage" not in body["missing_components"]


def test_explicit_poi_route_uses_dynamic_rail_provider_search():
    response = client.post(
        "/api/travel/plan",
        json={"raw_user_input": "从上海东方明珠塔出发，到北京天安门，6月15号上午"},
    )
    assert response.status_code == 200
    body = response.json()
    plan_ids = [plan["plan_id"] for plan in body["plans"]]
    assert any(plan_id.startswith("plan_rail_direct_dynamic") for plan_id in plan_ids), plan_ids
    dynamic_rail = next(plan for plan in body["plans"] if plan["plan_id"].startswith("plan_rail_direct_dynamic"))
    rail_segment = next(segment for segment in dynamic_rail["segments"] if segment["segment_type"] == "RAIL")
    assert rail_segment["origin_station"] in {"上海虹桥", "上海站"}
    assert rail_segment["destination_station"] in {"北京西", "北京南"}
    assert "route_coverage" not in body["missing_components"]


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
            "schema_version": "1.17",
            "request_id": "req_missing",
            "idempotency_key": "idem_missing",
            "plan_id": "missing_plan",
            "change_type": "SEAT_TYPE",
            "target_segment_id": "seg_missing",
            "selected_option": {
                "option_type": "SEAT",
                "option_id": "seat_first",
                "option_value": "一等座",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_ONLY",
        },
    )
    assert missing_recalc.status_code == 404
    assert missing_recalc.json()["error_code"] == "HTTP_404"

    plan_response = client.post("/api/travel/plan", json={"raw_user_input": RAW_INPUT}).json()
    plan = _first_dynamic_rail_plan(plan_response["plans"])
    rail_segment = next(seg for seg in plan["segments"] if seg["segment_type"] == "RAIL")
    invalid_option = client.post(
        "/api/travel/recalculate",
        json={
            "schema_version": "1.17",
            "request_id": "req_invalid_option",
            "idempotency_key": "idem_invalid_option",
            "plan_id": plan["plan_id"],
            "change_type": "SEAT_TYPE",
            "target_segment_id": rail_segment["segment_id"],
            "selected_option": {
                "option_type": "SEAT",
                "option_id": "seat_missing",
                "option_value": "不存在座席",
                "source_option_version": "provider_test_v1",
            },
            "recalculate_scope": "PLAN_ONLY",
        },
    )
    assert invalid_option.status_code == 400
    assert invalid_option.json()["schema_version"] == "1.17"
    assert invalid_option.json()["error_code"] == "HTTP_400"
