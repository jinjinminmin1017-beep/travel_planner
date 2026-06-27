from datetime import date

from app.data_sources import rail_providers
from app.data_sources.rail_providers import (
    AuthorizedRailPartnerProvider,
    IRailConnectionsProvider,
    RailConnectionRequest,
    RailProviderSearchResult,
    RailSearchRequest,
    build_enabled_rail_connection_providers,
    search_rail_offers_with_enabled_provider_result,
    search_rail_connections_with_enabled_provider_result,
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


class _FakeIRailClient:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _irail_connections_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


class _FakeJuheRailClient:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _juhe_train_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_juhe_train_query_maps_real_response_shape():
    client = _FakeJuheRailClient()
    provider = AuthorizedRailPartnerProvider(
        api_key="juhe-key",
        base_url="https://apis.juhe.cn/fapigw/train/query",
        client=client,
    )

    offers = provider.search_offers(
        RailSearchRequest(
            train_number="G234",
            origin_station="上海虹桥",
            destination_station="青岛北",
            departure_date=date(2026, 6, 20),
        )
    )

    assert client.calls[0][0] == "https://apis.juhe.cn/fapigw/train/query"
    assert "Authorization" not in client.calls[0][1]["headers"]
    assert client.calls[0][1]["params"] == {
        "key": "juhe-key",
        "search_type": "1",
        "departure_station": "上海虹桥",
        "arrival_station": "青岛北",
        "date": "2026-06-20",
        "filter": "G",
        "enable_booking": "2",
        "departure_time_range": "",
    }

    offer = offers[0]
    assert offer.train_number == "G234"
    assert offer.origin_station == "上海虹桥"
    assert offer.destination_station == "青岛北"
    assert offer.departure_at.isoformat() == "2026-06-20T09:48:00"
    assert offer.arrival_at.isoformat() == "2026-06-20T15:38:00"
    assert offer.duration_minutes == 350
    assert [seat.seat_type for seat in offer.seat_options] == ["商务座", "一等座", "二等座"]
    assert [seat.price.amount_minor for seat in offer.seat_options] == [162750, 86700, 52600]
    assert [seat.availability for seat in offer.seat_options] == ["LIMITED", "AVAILABLE", "NO_TICKET"]
    assert offer.data_source.source_name == "Juhe Train Query API"


def test_juhe_train_query_does_not_substitute_another_train_number():
    client = _FakeJuheRailClient()
    provider = AuthorizedRailPartnerProvider(
        api_key="juhe-key",
        base_url="https://apis.juhe.cn/fapigw/train/query",
        client=client,
    )

    offers = provider.search_offers(
        RailSearchRequest(
            train_number="G999",
            origin_station="上海虹桥",
            destination_station="青岛北",
            departure_date=date(2026, 6, 20),
        )
    )

    assert offers == []


def test_juhe_station_pair_query_leaves_filter_empty_without_train_number():
    client = _FakeJuheRailClient()
    provider = AuthorizedRailPartnerProvider(
        api_key="juhe-key",
        base_url="https://apis.juhe.cn/fapigw/train/query",
        client=client,
    )

    provider.search_offers(
        RailSearchRequest(
            train_number="",
            origin_station="上海虹桥",
            destination_station="温州南",
            departure_date=date(2026, 6, 28),
        )
    )

    assert client.calls[0][1]["params"]["filter"] == ""


def test_irail_connections_maps_real_response():
    client = _FakeIRailClient()
    provider = IRailConnectionsProvider(client=client, base_url="https://example.test", user_agent="test-app/1.0")

    connections = provider.search_connections(
        RailConnectionRequest(
            origin_station="Brussels-South",
            destination_station="Gent-Sint-Pieters",
            departure_date=date(2026, 6, 4),
            departure_time="1200",
            results=1,
        )
    )

    assert client.calls[0][0] == "https://example.test/connections/"
    assert client.calls[0][1]["headers"]["User-Agent"] == "test-app/1.0"
    assert client.calls[0][1]["params"]["from"] == "Brussels-South"
    assert client.calls[0][1]["params"]["to"] == "Gent-Sint-Pieters"
    assert client.calls[0][1]["params"]["date"] == "040626"
    assert client.calls[0][1]["params"]["time"] == "1200"
    assert client.calls[0][1]["params"]["format"] == "json"

    connection = connections[0]
    assert connection.connection_id == "0"
    assert connection.train_number == "IC 1526"
    assert connection.origin_station == "Brussels-South/Brussels-Midi"
    assert connection.destination_station == "Ghent-Sint-Pieters"
    assert connection.duration_minutes == 28
    assert connection.transfer_count == 0
    assert connection.platforms == ["12"]
    assert connection.vehicles == ["IC 1526"]
    assert connection.occupancy == "low"
    assert connection.canceled is False
    assert connection.data_source.source_id == "irail_connections"


def test_irail_connection_provider_is_enabled_by_default():
    providers = build_enabled_rail_connection_providers("DEV")
    assert [provider.source_id for provider in providers] == ["irail_connections"]


def test_irail_empty_response_reports_failure_without_fake_connection(monkeypatch):
    class _EmptyProvider:
        source_id = "irail_connections"

        def search_connections(self, request):
            return []

    monkeypatch.setattr("app.data_sources.rail_providers.build_enabled_rail_connection_providers", lambda environment=None: [_EmptyProvider()])

    result = search_rail_connections_with_enabled_provider_result(
        RailConnectionRequest(origin_station="Brussels-South", destination_station="Gent-Sint-Pieters"),
        "DEV",
    )

    assert result.connections == []
    assert result.attempted_source_ids == ["irail_connections"]
    assert result.failure_message == "irail_connections: empty response"


def test_rail_offer_search_respects_provider_qps_between_calls(monkeypatch):
    class _EmptyRailProvider:
        source_id = "rail_authorized_partner"

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
    monkeypatch.setenv("TRAVEL_SOURCE_RAIL_AUTHORIZED_PARTNER_MIN_INTERVAL_SECONDS", "1")
    rail_providers._LAST_PROVIDER_CALL_AT.clear()

    request = RailSearchRequest(train_number="", origin_station="上海虹桥", destination_station="北京南", departure_date=date(2026, 6, 24))
    first = search_rail_offers_with_enabled_provider_result(request)
    fake_time["now"] += 0.2
    second = search_rail_offers_with_enabled_provider_result(request)

    assert first.offers == []
    assert second.offers == []
    assert [round(value, 2) for value in slept] == [1.05]


def test_planner_blocks_rail_plans_when_real_rail_provider_is_empty(monkeypatch):
    def fake_empty_search(request, environment=None):
        return RailProviderSearchResult(offers=[], attempted_source_ids=["rail_authorized_partner"], failure_message="empty real response")

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_empty_search)
    request = TravelRequest(
        request_id="req_no_simulated_rail_fallback",
        raw_user_input="2026-05-21 Shanghai to Qingdao",
        origin_text="Shanghai",
        destination_text="Qingdao",
        travel_date=date(2026, 5, 21),
        preferences=[RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, blocked_types, explanations, _ = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    assert blocked_types
    assert explanations
    assert any(failure.source_id == "rail_authorized_partner" and failure.failure_class == "CORE_FACT_FAILURE" for failure in failures)


def test_planner_reports_rail_provider_rate_limit_without_fake_plan(monkeypatch):
    def fake_rate_limited_search(request, environment=None):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_authorized_partner"],
            failure_message="rail_authorized_partner: juhe rail query failed: 超过每日可允许请求次数!",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_rate_limited_search)
    request = TravelRequest(
        request_id="req_rail_rate_limited",
        raw_user_input="2026-06-24 Shanghai to Beijing",
        origin_text="上海东方明珠塔",
        destination_text="北京天安门",
        travel_date=date(2026, 6, 24),
        preferences=[RecommendationType.CHEAPEST, RecommendationType.MOST_COMFORTABLE, RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, _, explanations, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_authorized_partner")
    assert failure.error_code == "RAIL_PROVIDER_RATE_LIMITED"
    assert "频率或配额限制" in failure.user_visible_message
    assert any("频率或配额限制" in item.user_visible_message for item in explanations)
    assert any("频率或配额限制" in warning for warning in warnings)


def test_planner_classifies_chinese_frequency_limit_as_rate_limited(monkeypatch):
    def fake_rate_limited_search(request, environment=None):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_authorized_partner"],
            failure_message="rail_authorized_partner: juhe rail query failed: 请求频率超过限制：每1秒限制1次，当前值：2",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_rate_limited_search)
    request = TravelRequest(
        request_id="req_rail_frequency_limited",
        raw_user_input="2026-06-27 上海到三亚",
        origin_text="上海静安寺",
        destination_text="海南三亚",
        travel_date=date(2026, 6, 27),
        preferences=[RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, _, _, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_authorized_partner")
    assert failure.error_code == "RAIL_PROVIDER_RATE_LIMITED"
    assert "频率或配额限制" in failure.user_visible_message
    assert any("频率或配额限制" in warning for warning in warnings)


def test_planner_classifies_all_empty_rail_pairs_as_no_direct_result(monkeypatch):
    def fake_empty_search(request, environment=None):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["rail_authorized_partner"],
            failure_message="rail_authorized_partner: empty response",
        )

    monkeypatch.setattr("app.services.planner.search_rail_offers_with_enabled_provider_result", fake_empty_search)
    request = TravelRequest(
        request_id="req_rail_empty_direct",
        raw_user_input="2026-06-27 上海到三亚",
        origin_text="上海静安寺",
        destination_text="海南三亚",
        travel_date=date(2026, 6, 27),
        preferences=[RecommendationType.BALANCED],
        preference_source="USER_EXPLICIT",
        hard_constraints=TravelHardConstraints(),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, failures, missing, _, _, warnings = build_plans(request)

    assert plans
    assert not any(plan.plan_type in {PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL} for plan in plans)
    assert "rail_core_fact" in missing
    failure = next(item for item in failures if item.source_id == "rail_authorized_partner")
    assert failure.error_code == "RAIL_PROVIDER_EMPTY"
    assert "暂未返回可验证的直达车次" in failure.user_visible_message
    assert any("暂未返回可验证的直达车次" in warning for warning in warnings)


def _irail_connections_payload():
    return {
        "version": "1.4",
        "timestamp": "1780531713",
        "connection": [
            {
                "id": "0",
                "departure": {
                    "station": "Brussels-South/Brussels-Midi",
                    "time": "1780543740",
                    "vehicle": "BE.NMBS.IC1526",
                    "vehicleinfo": {"shortname": "IC 1526", "number": "1526"},
                    "platform": "12",
                    "canceled": "0",
                    "occupancy": {"name": "low"},
                },
                "arrival": {
                    "station": "Ghent-Sint-Pieters",
                    "time": "1780545420",
                    "vehicle": "BE.NMBS.IC1526",
                    "vehicleinfo": {"shortname": "IC 1526", "number": "1526"},
                    "platform": "12",
                    "canceled": "0",
                },
                "duration": "1680",
                "vias": {"number": "0", "via": []},
            }
        ],
    }


def _juhe_train_payload():
    return {
        "reason": "success",
        "error_code": 0,
        "result": [
            {
                "train_no": "G234",
                "departure_station": "上海虹桥",
                "arrival_station": "青岛北",
                "departure_time": "09:48",
                "arrival_time": "15:38",
                "duration": "05:50",
                "prices": [
                    {"seat_type_code": "9", "seat_name": "商务座", "price": 1627.5, "num": "少"},
                    {"seat_type_code": "M", "seat_name": "一等座", "price": 867, "num": "有"},
                    {"seat_type_code": "O", "seat_name": "二等座", "price": 526, "num": "无"},
                ],
            }
        ],
    }
