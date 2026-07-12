from datetime import date

from app.data_sources.map_providers import MapRouteProviderResult
from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


def test_planner_marks_rule_based_transfer_fallback_when_real_map_provider_is_empty(monkeypatch):
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

    assert plans
    assert "map_route" in missing
    assert any("该接驳路线暂未取得地图结果" in warning for warning in warnings)
    assert any(failure.source_id == "amap_route" and failure.fallback_used for failure in failures)
    transfer_segments = [segment for plan in plans for segment in plan.segments if getattr(segment, "segment_type", None) == "LOCAL_TRANSFER"]
    assert transfer_segments
    assert all(segment.data_source.source_id == "internal_calc" for segment in transfer_segments)
