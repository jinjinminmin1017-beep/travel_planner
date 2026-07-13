from datetime import date

from app.data_sources.map_providers import MapRouteProviderResult
from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


def test_planner_blocks_plans_instead_of_simulating_transfer_when_map_provider_is_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.planner.estimate_route_with_enabled_provider_result",
        lambda request, environment=None: MapRouteProviderResult(
            estimate=None,
            attempted_source_ids=["amap_route"],
            failure_message="amap_route: empty route result",
        ),
    )
    travel_request = TravelRequest(
        request_id="req_no_simulated_map",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.MOST_COMFORTABLE, RecommendationType.CHEAPEST, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(prefer_comfort=True),
    )

    plans, failures, missing, _, _, warnings = build_plans(travel_request)

    assert plans == []
    assert "map_route" in missing
    assert any("无法形成完整门到门方案" in warning for warning in warnings)
    assert any(failure.error_code == "MAP_TRANSFER_UNAVAILABLE" and not failure.fallback_used for failure in failures)
    assert all(
        getattr(segment, "route_status", None) != "RULE_ESTIMATED"
        for plan in plans
        for segment in plan.segments
    )
