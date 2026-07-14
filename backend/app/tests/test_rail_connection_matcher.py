from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.data_sources.rail_providers import RailOffer, rail_data_source_metadata
from app.models.schemas import LocalTransferSegment, RiskLevel, SeatOption, TransportMode, money
from app.services.rail_connection_matcher import (
    RailConnectionPolicy,
    match_rail_connections,
    rail_connection_matcher_v2_enabled,
    rail_connection_policy_from_env,
)

SHANGHAI_TZ = timezone(timedelta(hours=8))
DAY = date(2026, 7, 15)
SOURCE = rail_data_source_metadata("rail_12306_public_query", "12306 Public Ticket Query")


def _offer(
    train_number: str,
    origin: str,
    destination: str,
    departure: tuple[int, int],
    arrival: tuple[int, int],
    *,
    origin_code: str,
    destination_code: str,
) -> RailOffer:
    departure_at = datetime.combine(DAY, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(
        hour=departure[0], minute=departure[1]
    )
    arrival_at = datetime.combine(DAY, datetime.min.time(), tzinfo=SHANGHAI_TZ).replace(
        hour=arrival[0], minute=arrival[1]
    )
    return RailOffer(
        train_number=train_number,
        origin_station=origin,
        destination_station=destination,
        departure_at=departure_at,
        arrival_at=arrival_at,
        duration_minutes=int((arrival_at - departure_at).total_seconds() // 60),
        stop_sequence=[origin, destination],
        seat_options=[
            SeatOption(
                option_id=f"seat_{train_number}",
                seat_type="二等座",
                price=money(30000),
                availability="AVAILABLE",
                source_option_version=f"test_{train_number}",
                data_source=SOURCE,
            )
        ],
        data_source=SOURCE,
        origin_station_code=origin_code,
        destination_station_code=destination_code,
    )


def _cross_station_segment(origin: str = "北京西", destination: str = "北京北", minutes: int = 20) -> LocalTransferSegment:
    return LocalTransferSegment(
        segment_id="seg_cross_station",
        origin=origin,
        destination=destination,
        transfer_mode=TransportMode.TAXI,
        distance_meters=8000,
        duration_minutes=minutes,
        estimated_cost=money(3000, estimated=True),
        traffic_risk=RiskLevel.MEDIUM,
        walking_distance_meters=None,
        option_id="transfer_taxi",
        available_options=["transfer_taxi"],
        transfer_options=[],
        data_source=SOURCE,
        route_status="PRIMARY_VERIFIED",
        route_error_code=None,
        redirect_info=None,
    )


def _match(first: list[RailOffer], second: list[RailOffer], **policy_updates):
    policy = RailConnectionPolicy(**policy_updates)
    return match_rail_connections(
        first,
        second,
        policy=policy,
        resolve_cross_station_transfer=lambda _first, _second: None,
    )


def test_matcher_uses_offer_after_the_legacy_first_two_window():
    first = [_offer("G502", "岳阳东", "北京西", (7, 0), (14, 12), origin_code="YIQ", destination_code="BXP")]
    second = [
        _offer("D1", "北京西", "张家口", (13, 40), (14, 40), origin_code="BXP", destination_code="ZKP"),
        _offer("D2", "北京西", "张家口", (14, 30), (15, 30), origin_code="BXP", destination_code="ZKP"),
        _offer("D6649", "北京西", "张家口", (14, 58), (16, 3), origin_code="BXP", destination_code="ZKP"),
    ]

    candidates, metrics = _match(first, second)

    assert [(item.first_offer.train_number, item.second_offer.train_number) for item in candidates] == [("G502", "D6649")]
    assert candidates[0].wait_minutes == 46
    assert metrics.second_offer_count == 3
    assert metrics.rejected_departed_before_arrival == 1
    assert metrics.rejected_transfer_buffer == 1


def test_minimum_transfer_boundary_rejects_44_minutes_and_accepts_45():
    first = [_offer("G1", "甲站", "中转站", (8, 0), (10, 0), origin_code="AAA", destination_code="HUB")]
    second = [
        _offer("G2", "中转站", "乙站", (10, 44), (12, 0), origin_code="HUB", destination_code="BBB"),
        _offer("G3", "中转站", "乙站", (10, 45), (12, 1), origin_code="HUB", destination_code="BBB"),
    ]

    candidates, metrics = _match(first, second)

    assert [item.second_offer.train_number for item in candidates] == ["G3"]
    assert metrics.rejected_transfer_buffer == 1


def test_maximum_wait_boundary_accepts_360_minutes_and_rejects_361():
    first = [_offer("G1", "甲站", "中转站", (8, 0), (10, 0), origin_code="AAA", destination_code="HUB")]
    second = [
        _offer("G2", "中转站", "乙站", (16, 0), (17, 0), origin_code="HUB", destination_code="BBB"),
        _offer("G3", "中转站", "乙站", (16, 1), (17, 1), origin_code="HUB", destination_code="BBB"),
    ]

    candidates, metrics = _match(first, second)

    assert [item.second_offer.train_number for item in candidates] == ["G2"]
    assert metrics.rejected_max_wait == 1


def test_same_station_identity_does_not_call_cross_station_resolver():
    first = [_offer("G1", "甲站", "北京西", (8, 0), (10, 0), origin_code="AAA", destination_code="BXP")]
    second = [_offer("G2", "北京西站", "乙站", (10, 45), (12, 0), origin_code="BXP", destination_code="BBB")]
    calls: list[tuple[str, str]] = []

    candidates, _ = match_rail_connections(
        first,
        second,
        policy=RailConnectionPolicy(),
        resolve_cross_station_transfer=lambda left, right: calls.append((left.destination_station, right.origin_station)),
    )

    assert len(candidates) == 1
    assert candidates[0].same_station is True
    assert candidates[0].cross_station_transfer is None
    assert calls == []


def test_cross_station_requires_verified_route_and_dynamic_buffer():
    first = [_offer("G1", "甲站", "北京西", (8, 0), (10, 0), origin_code="AAA", destination_code="BXP")]
    second = [
        _offer("G2", "北京北", "乙站", (10, 49), (12, 0), origin_code="VAP", destination_code="BBB"),
        _offer("G3", "北京北", "乙站", (10, 50), (12, 1), origin_code="VAP", destination_code="BBB"),
    ]

    candidates, metrics = match_rail_connections(
        first,
        second,
        policy=RailConnectionPolicy(),
        resolve_cross_station_transfer=lambda _first, _second: _cross_station_segment(minutes=20),
    )

    assert [item.second_offer.train_number for item in candidates] == ["G3"]
    assert candidates[0].required_transfer_minutes == 50
    assert candidates[0].cross_station_transfer is not None
    assert metrics.rejected_transfer_buffer == 1

    blocked, blocked_metrics = match_rail_connections(
        first,
        second,
        policy=RailConnectionPolicy(),
        resolve_cross_station_transfer=lambda _first, _second: None,
    )
    assert blocked == []
    assert blocked_metrics.rejected_cross_station_route == 2


def test_matcher_deduplicates_alias_query_facts_by_station_code():
    first_offer = _offer("G1", "甲站", "北京西", (8, 0), (10, 0), origin_code="AAA", destination_code="BXP")
    second_offer = _offer("G2", "北京西", "乙站", (10, 45), (12, 0), origin_code="BXP", destination_code="BBB")

    candidates, metrics = _match([first_offer, first_offer], [second_offer, second_offer])

    assert len(candidates) == 1
    assert metrics.first_offer_count == 1
    assert metrics.second_offer_count == 1


def test_invalid_environment_config_uses_safe_defaults(monkeypatch, caplog):
    monkeypatch.setenv("TRAVEL_RAIL_CONNECTION_MATCHER_V2", "sometimes")
    monkeypatch.setenv("TRAVEL_RAIL_MIN_TRANSFER_MINUTES", "0")
    monkeypatch.setenv("TRAVEL_RAIL_MAX_TRANSFER_WAIT_MINUTES", "invalid")

    assert rail_connection_matcher_v2_enabled() is True
    policy = rail_connection_policy_from_env()

    assert policy.min_same_station_transfer_minutes == 45
    assert policy.max_transfer_wait_minutes == 360
    assert "rail_connection_config_invalid" in caplog.text


def test_matcher_v2_feature_flag_can_disable_complete_offer_window(monkeypatch):
    monkeypatch.setenv("TRAVEL_RAIL_CONNECTION_MATCHER_V2", "false")

    assert rail_connection_matcher_v2_enabled() is False
