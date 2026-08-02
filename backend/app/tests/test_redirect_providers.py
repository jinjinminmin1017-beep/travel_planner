from datetime import date, datetime
from urllib.parse import parse_qsl, urlparse

from app.data_sources.provider_booking import ProviderBookingReference
from app.data_sources.redirect_providers import build_fliggy_redirect, create_booking_redirect
from app.models.schemas import BookingRedirectRequest, PlanType, RecommendationType, RiskLevel, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import _flight, _plan as build_test_plan, build_plans


def _plan(plan_id: str | None = None):
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
    if plan_id is None:
        return next(item for item in plans if item.plan_id.startswith("plan_rail_direct_dynamic"))
    return next(item for item in plans if item.plan_id == plan_id)


def _flight_plan():
    segment = _flight(
        "seg_flight_redirect",
        "MU5511",
        "上海虹桥机场",
        "青岛胶东机场",
        date(2026, 5, 21),
        11,
        20,
        13,
        0,
        88800,
    )
    return build_test_plan(
        "plan_flight_redirect",
        "航司跳转测试",
        PlanType.DIRECT_FLIGHT,
        [segment],
        8.0,
        RiskLevel.LOW,
        "redirect test",
        "redirect test",
    )


def _redirect_request(plan, redirect_type: str, segment_id: str | None = None) -> BookingRedirectRequest:
    return BookingRedirectRequest(
        request_id="req_redirect_provider",
        idempotency_key="idem_redirect_provider",
        plan_id=plan.plan_id,
        segment_id=segment_id,
        redirect_type=redirect_type,  # type: ignore[arg-type]
    )


def test_retired_rail_redirect_returns_manual_fallback():
    plan = _plan()
    rail_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "RAIL")

    redirect = create_booking_redirect(_redirect_request(plan, "RAIL_12306", rail_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is False
    assert redirect.url is None
    assert redirect.transaction_boundary == "REDIRECT_ONLY"
    assert redirect.generated_at.datetime < redirect.expires_at.datetime
    assert redirect.data_source.source_id == "redirect_fallback"


def test_map_uri_redirect_uses_default_enabled_amap_provider():
    plan = _plan()
    transfer_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "LOCAL_TRANSFER")

    redirect = create_booking_redirect(_redirect_request(plan, "MAP_NAVIGATION", transfer_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is True
    assert redirect.url and redirect.url.startswith("https://uri.amap.com/navigation?")
    assert redirect.data_source.source_id == "amap_uri_redirect"
    params = dict(parse_qsl(urlparse(redirect.url).query))
    assert "order" not in params
    assert "pay" not in params


def test_retired_airline_redirect_returns_manual_fallback():
    plan = _flight_plan()
    flight_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "FLIGHT")

    redirect = create_booking_redirect(_redirect_request(plan, "AIRLINE", flight_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is False
    assert redirect.url is None
    assert redirect.data_source.source_id == "redirect_fallback"


def test_fliggy_redirect_is_read_from_plan_and_bound_to_segment():
    plan = _flight_plan()
    flight_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "FLIGHT")
    stored = build_fliggy_redirect(
        reference=ProviderBookingReference(
            source_id="fliggy_flyai",
            redirect_url="https://router.feizhu.com/flight/item-001",
            item_fingerprint="a" * 64,
            fetched_at=datetime.now().astimezone(),
        ),
        plan_id=plan.plan_id,
        segment_id=flight_segment.segment_id,
        metadata=flight_segment.data_source,
    )
    plan.booking_redirects.append(stored)

    redirect = create_booking_redirect(_redirect_request(plan, "FLIGGY", flight_segment.segment_id), plan, environment="DEV")

    assert redirect == stored
    assert redirect.url == "https://router.feizhu.com/flight/item-001"


def test_fliggy_redirect_cannot_be_reused_for_another_segment():
    plan = _plan()
    segments = list(plan.segments)
    first = segments[0]
    second = segments[1]
    plan.booking_redirects.append(
        build_fliggy_redirect(
            reference=ProviderBookingReference(
                source_id="fliggy_flyai",
                redirect_url="https://router.feizhu.com/train/item-001",
                item_fingerprint="b" * 64,
                fetched_at=datetime.now().astimezone(),
            ),
            plan_id=plan.plan_id,
            segment_id=first.segment_id,
            metadata=first.data_source,
        )
    )

    redirect = create_booking_redirect(_redirect_request(plan, "FLIGGY", second.segment_id), plan, environment="DEV")

    assert redirect.url_available is False
    assert redirect.url is None


def test_ride_hailing_redirect_is_redirect_only_navigation():
    plan = _plan()
    transfer_segment = next(segment for segment in plan.segments if getattr(segment, "segment_type", None) == "LOCAL_TRANSFER")

    redirect = create_booking_redirect(_redirect_request(plan, "RIDE_HAILING", transfer_segment.segment_id), plan, environment="DEV")

    assert redirect.url_available is True
    assert redirect.transaction_boundary == "REDIRECT_ONLY"
    assert redirect.url and "uri.amap.com/navigation" in redirect.url
    assert "order" not in redirect.url.lower()
    assert "pay" not in redirect.url.lower()
