from datetime import date

from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


def test_planner_does_not_fallback_to_simulated_data_when_real_map_provider_is_empty(monkeypatch):
    monkeypatch.setattr("app.services.planner.estimate_route_with_enabled_provider", lambda request, environment=None: None)
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

    try:
        build_plans(travel_request)
    except ValueError as exc:
        assert "real map route provider unavailable" in str(exc)
    else:
        raise AssertionError("planner must not create simulated local transfers when real map provider is unavailable")
