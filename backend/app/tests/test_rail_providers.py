from datetime import date

import pytest

from app.data_sources import rail_providers
from app.data_sources.rail_providers import (
    Official12306RailProvider,
    RailProviderError,
    RailProviderSearchResult,
    RailSearchRequest,
    search_rail_offers_with_enabled_provider_result,
    station_code_for_name,
)
from app.models.schemas import PlanType, RecommendationType, TravelHardConstraints, TravelRequest, TravelSoftPreferences
from app.services.planner import build_plans


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Fake12306Client:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _left_ticket_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/otn/leftTicket/init"):
            return _FakeResponse({})
        return _FakeResponse(self.payload)


def test_station_code_lookup_uses_imported_12306_catalog():
    assert station_code_for_name("上海虹桥") == "AOH"
    assert station_code_for_name("上海虹桥站") == "AOH"
    assert station_code_for_name("北京南") == "VNP"


def test_12306_public_query_maps_ticket_response_shape():
    client = _Fake12306Client()
    provider = Official12306RailProvider(client=client, base_url="https://kyfw.12306.cn", cache_ttl_seconds=0)

    offers = provider.search_offers(
        RailSearchRequest(
            train_number="G532",
            origin_station="上海虹桥",
            destination_station="北京南",
            departure_date=date(2026, 7, 10),
        )
    )

    assert client.calls[0][0] == "https://kyfw.12306.cn/otn/leftTicket/init"
    assert client.calls[1][0] == "https://kyfw.12306.cn/otn/leftTicket/queryG"
    assert client.calls[1][1]["params"] == {
        "leftTicketDTO.train_date": "2026-07-10",
        "leftTicketDTO.from_station": "AOH",
        "leftTicketDTO.to_station": "VNP",
        "purpose_codes": "ADULT",
    }

    offer = offers[0]
    assert offer.train_number == "G532"
    assert offer.origin_station == "上海虹桥"
    assert offer.destination_station == "北京南"
    assert offer.departure_at.isoformat() == "2026-07-10T06:31:00+08:00"
    assert offer.arrival_at.isoformat() == "2026-07-10T12:18:00+08:00"
    assert offer.duration_minutes == 347
    assert [seat.seat_type for seat in offer.seat_options] == ["商务座", "一等座", "二等座"]
    assert [seat.price.amount_minor for seat in offer.seat_options] == [187000, 96700, 57600]
    assert [seat.availability for seat in offer.seat_options] == ["AVAILABLE", "LIMITED", "AVAILABLE"]
    assert offer.data_source.source_id == "rail_12306_public_query"


def test_12306_public_query_does_not_substitute_another_train_number():
    client = _Fake12306Client()
    provider = Official12306RailProvider(client=client, base_url="https://kyfw.12306.cn", cache_ttl_seconds=0)

    offers = provider.search_offers(
        RailSearchRequest(
            train_number="G999",
            origin_station="上海虹桥",
            destination_station="北京南",
            departure_date=date(2026, 7, 10),
        )
    )

    assert offers == []


def test_12306_public_query_blocks_unpriced_available_seats():
    payload = _left_ticket_payload(_left_ticket_row(price_blob="", second_class="有"))
    provider = Official12306RailProvider(client=_Fake12306Client(payload), base_url="https://kyfw.12306.cn", cache_ttl_seconds=0)

    with pytest.raises(RailProviderError, match="no priced available seats"):
        provider.search_offers(
            RailSearchRequest(
                train_number="",
                origin_station="上海虹桥",
                destination_station="北京南",
                departure_date=date(2026, 7, 10),
            )
        )


def test_12306_public_query_filters_no_ticket_seats():
    payload = _left_ticket_payload(_left_ticket_row(second_class="无", first_class="无", business="无"))
    provider = Official12306RailProvider(client=_Fake12306Client(payload), base_url="https://kyfw.12306.cn", cache_ttl_seconds=0)

    with pytest.raises(RailProviderError, match="no priced available seats"):
        provider.search_offers(
            RailSearchRequest(
                train_number="",
                origin_station="上海虹桥",
                destination_station="北京南",
                departure_date=date(2026, 7, 10),
            )
        )


def test_rail_offer_search_respects_12306_public_query_qps_between_calls(monkeypatch):
    class _EmptyRailProvider:
        source_id = "rail_12306_public_query"

        def search_offers(self, request):
            return []

    fake_time = {"now": 100.0}
    slept: list[float] = []

    def fake_sleep(seconds):
        slept.append(seconds)
        fake_time["now"] += seconds

    monkeypatch.setattr("app.data_sources.rail_providers.build_enabled_rail_providers", lambda environment=None: [_EmptyRailProvider()])
    monkeypatch.setattr(rail_providers, "_monotonic", lambda: fake_time["now"])
    monkeypatch.setattr(rail_providers, "_sleep", fake_sleep)
    monkeypatch.setenv("TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_MIN_INTERVAL_SECONDS", "1")
    rail_providers._LAST_PROVIDER_CALL_AT.clear()

    request = RailSearchRequest(train_number="", origin_station="上海虹桥", destination_station="北京南", departure_date=date(2026, 7, 10))
    first = search_rail_offers_with_enabled_provider_result(request)
    fake_time["now"] += 0.2
    second = search_rail_offers_with_enabled_provider_result(request)

    assert first.offers == []
    assert second.offers == []
    assert [round(value, 2) for value in slept] == [0.8]


def test_planner_blocks_rail_plans_when_12306_public_query_is_empty(monkeypatch):
    def fake_empty_search(request, environment=None):
        return RailProviderSearchResult(offers=[], attempted_source_ids=["rail_12306_public_query"], failure_message="empty real response")

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_empty_search)
    request = _travel_request("req_no_simulated_rail_fallback", "2026-05-21 Shanghai to Qingdao", "Shanghai", "Qingdao", date(2026, 5, 21))

    plans, failures, missing, blocked_types, explanations, _ = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    assert blocked_types
    assert explanations
    assert any(failure.source_id == "rail_12306_public_query" and failure.failure_class == "CORE_FACT_FAILURE" for failure in failures)


def test_planner_reports_12306_rate_limit_without_fake_plan(monkeypatch):
    rail_calls = []

    def fake_rate_limited_search(request, environment=None):
        rail_calls.append((request.origin_station, request.destination_station))
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_12306_public_query"],
            failure_message="rail_12306_public_query: 12306 public query failed: 请求频率超过限制",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_rate_limited_search)
    request = _travel_request("req_rail_rate_limited", "2026-06-24 Shanghai to Beijing", "上海东方明珠塔", "北京天安门", date(2026, 6, 24))

    plans, failures, missing, _, explanations, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_12306_public_query")
    assert failure.error_code == "RAIL_PROVIDER_RATE_LIMITED"
    assert "访问限制" in failure.user_visible_message
    assert any("访问限制" in item.user_visible_message for item in explanations)
    assert any("访问限制" in warning for warning in warnings)
    assert len(rail_calls) == 1


def test_planner_classifies_missing_12306_price_as_core_fact_failure(monkeypatch):
    def fake_missing_price_search(request, environment=None):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_12306_public_query"],
            failure_message="rail_12306_public_query: 12306 public query returned no priced available seats for G532",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_missing_price_search)
    request = _travel_request("req_rail_missing_price", "2026-06-27 上海到三亚", "上海静安寺", "海南三亚", date(2026, 6, 27))

    plans, failures, missing, _, _, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_12306_public_query")
    assert failure.error_code == "RAIL_PROVIDER_MISSING_PRICE"
    assert "有票和票价" in failure.user_visible_message
    assert any("有票和票价" in warning for warning in warnings)


def test_planner_classifies_all_empty_12306_pairs_as_no_direct_result(monkeypatch):
    def fake_empty_search(request, environment=None):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_12306_public_query"],
            failure_message="rail_12306_public_query: empty response",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_empty_search)
    request = _travel_request("req_rail_empty_direct", "2026-06-27 上海到三亚", "上海静安寺", "海南三亚", date(2026, 6, 27))

    plans, failures, missing, _, _, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_12306_public_query")
    assert failure.error_code == "RAIL_PROVIDER_EMPTY"
    assert "有票直达车次" in failure.user_visible_message
    assert any("有票直达车次" in warning for warning in warnings)


def _travel_request(request_id: str, raw: str, origin: str, destination: str, travel_date: date) -> TravelRequest:
    return TravelRequest(
        request_id=request_id,
        raw_user_input=raw,
        origin_text=origin,
        destination_text=destination,
        travel_date=travel_date,
        preferences=[RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )


def _left_ticket_payload(row: str | None = None):
    return {
        "httpstatus": 200,
        "status": True,
        "data": {
            "map": {"AOH": "上海虹桥", "VNP": "北京南"},
            "result": [row or _left_ticket_row()],
        },
    }


def _left_ticket_row(
    *,
    train_number: str = "G532",
    business: str = "12",
    first_class: str = "少",
    second_class: str = "有",
    price_blob: str = "9187000012M096700021O057600021O057603066",
) -> str:
    parts = [""] * 58
    parts[1] = "预订"
    parts[2] = "5l0000G53201"
    parts[3] = train_number
    parts[4] = "AOH"
    parts[5] = "VNP"
    parts[6] = "AOH"
    parts[7] = "VNP"
    parts[8] = "06:31"
    parts[9] = "12:18"
    parts[10] = "05:47"
    parts[11] = "Y"
    parts[13] = "20260710"
    parts[16] = "01"
    parts[17] = "09"
    parts[30] = second_class
    parts[31] = first_class
    parts[32] = business
    parts[34] = "90M0O0W0"
    parts[35] = "9MOO"
    parts[39] = price_blob
    return "|".join(parts)
