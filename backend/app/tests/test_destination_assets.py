from datetime import date

from app.models.schemas import RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.destination_assets import resolve_destination_presentation


def make_request(raw: str, destination: str) -> TravelRequest:
    return TravelRequest(
        request_id="req_destination_asset_test",
        raw_user_input=raw,
        origin_text="Shanghai",
        destination_text=destination,
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.CHEAPEST],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )


def test_destination_asset_prefers_structured_destination_over_origin():
    presentation = resolve_destination_presentation(make_request("from Shanghai to Qingdao", "Qingdao hotel"))

    assert presentation.destination_key == "qingdao"
    assert presentation.display_name == "青岛"
    assert presentation.hero_image_url == "/destination-scenes/qingdao-pier.jpg"
    assert presentation.focal_point == "center 46%"


def test_destination_asset_falls_back_to_generic():
    presentation = resolve_destination_presentation(make_request("from Shanghai to Atlantis", "Atlantis"))

    assert presentation.destination_key == "generic"
    assert presentation.display_name == "目的地"
    assert presentation.hero_image_url == "/destination-scenes/generic.svg"
