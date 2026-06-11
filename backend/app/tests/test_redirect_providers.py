from datetime import date

from app.data_sources.redirect_providers import create_booking_redirect
from app.models.schemas import BookingRedirectRequest, RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


def _plan(plan_id: str = "plan_rail_direct_shqd"):
    request = TravelRequest(
        request_id="req_redirect_provider",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )
    plans, *_ = build_plans(request)
    return next(item for item in plans if item.plan_id == plan_id)


def _redirect_request(plan, redirect_type: str, segment_id: str | None = None) -> BookingRedirectRequest:
    return BookingRedirectRequest(
        request_id="req_redirect_provider",
        idempotency_key="idem_redirect_provider",
        plan_id=plan.plan_id,
        segment_id=segment_id,
        redirect_type=redirect_type,  # type: ignore[arg-type]
    )


def test_rail_12306_redirect_uses_default_enabled_official_provider():
    plan = _plan()
    rail_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "RAIL")

    redirect = create_booking_redirect(_redirect_request(plan, "RAIL_12306", rail_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is True
    assert redirect.url == "https://www.12306.cn/index/"
    assert redirect.transaction_boundary == "REDIRECT_ONLY"
    assert redirect.data_source.source_id == "rail_12306_redirect"
    assert "12306" in (redirect.fallback_instruction or "")


def test_map_uri_redirect_uses_default_enabled_amap_provider():
    plan = _plan()
    transfer_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "LOCAL_TRANSFER")

    redirect = create_booking_redirect(_redirect_request(plan, "MAP_NAVIGATION", transfer_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is True
    assert redirect.url and redirect.url.startswith("https://uri.amap.com/navigation?")
    assert redirect.data_source.source_id == "amap_uri_redirect"


def test_airline_redirect_uses_default_enabled_official_provider():
    plan = _plan("plan_flight_direct_shqd")
    flight_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "FLIGHT")

    redirect = create_booking_redirect(_redirect_request(plan, "AIRLINE", flight_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is True
    assert redirect.url == "https://www.ceair.com/"
    assert redirect.data_source.source_id == "airline_official_redirect"


def test_ota_redirect_requires_partner_env(monkeypatch):
    plan = _plan()

    monkeypatch.setenv("TRAVEL_SOURCE_OTA_PARTNER_REDIRECT_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_OTA_PARTNER_REDIRECT_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("OTA_PARTNER_ID", "partner_test")
    missing_base_url = create_booking_redirect(_redirect_request(plan, "OTA"), plan, environment="DEV")
    assert missing_base_url.url_available is False

    monkeypatch.setenv("OTA_PARTNER_BASE_URL", "https://partner.example/search")
    redirect = create_booking_redirect(_redirect_request(plan, "OTA"), plan, environment="DEV")
    assert redirect.url_available is True
    assert redirect.url and redirect.url.startswith("https://partner.example/search?")
    assert "partner_id=partner_test" in redirect.url
    assert redirect.data_source.source_id == "ota_partner_redirect"
