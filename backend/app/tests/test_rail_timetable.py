from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.data_sources.config_loader import (
    DataSourceConfigurationError,
    load_rail_timetable_settings,
)
from app.data_sources.provider_booking import ProviderBookingReference
from app.data_sources.rail_12306_timetable_provider import (
    Rail12306TimetableProvider,
    RailTimetableAccessControlError,
)
from app.data_sources.rail_providers import (
    RailOffer,
    RailProviderOutcome,
    RailProviderSearchResult,
    rail_data_source_metadata,
)
from app.models.schemas import (
    GeoPoint,
    PlanType,
    RecommendationType,
    SeatOption,
    StationCandidate,
    TransportMode,
    TravelHardConstraints,
    TravelRequest,
    TravelSoftPreferences,
    money,
)
from app.services.location_resolver import (
    INTERNAL_LOCATION_SOURCE,
    PlanningRouteNodes,
    station_candidates_for_location,
)
from app.services.planner import build_plans
from app.services.rail_inventory_verifier import (
    RailInventoryCandidateResult,
    RailInventoryVerificationDiagnostics,
    RailInventoryVerificationResult,
    RailInventoryVerifier,
)
from app.services.rail_route_search import RailRouteSearch, RailScheduleCandidate, RailScheduleLeg
from app.services.rail_timetable_store import (
    RailServiceInput,
    RailStopTimeInput,
    RailTimetableStore,
    RailTimetableStoreError,
)
from scripts.import_12306_timetable import _mark_checkpoint_paused


UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))


def test_rail_timetable_settings_defaults_and_validation() -> None:
    defaults = load_rail_timetable_settings({})
    assert defaults.snapshot_enabled is False
    assert defaults.local_routing_enabled is False
    assert defaults.horizon_days == 15
    assert defaults.refresh_at == "03:30"

    enabled = load_rail_timetable_settings(
        {
            "TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED": "true",
            "TRAVEL_RAIL_LOCAL_ROUTING_ENABLED": "true",
            "TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED": "true",
            "TRAVEL_RAIL_TIMETABLE_HORIZON_DAYS": "15",
            "TRAVEL_RAIL_TIMETABLE_RETENTION_DAYS": "60",
            "TRAVEL_RAIL_TIMETABLE_REFRESH_AT": "02:15",
        }
    )
    assert enabled.snapshot_enabled and enabled.local_routing_enabled and enabled.refresh_enabled
    assert enabled.retention_days == 60

    with pytest.raises(DataSourceConfigurationError, match="requires"):
        load_rail_timetable_settings({"TRAVEL_RAIL_LOCAL_ROUTING_ENABLED": "true"})
    with pytest.raises(DataSourceConfigurationError, match="HH:mm"):
        load_rail_timetable_settings({"TRAVEL_RAIL_TIMETABLE_REFRESH_AT": "25:99"})


def test_batch_activation_is_idempotent_and_failed_staging_preserves_active(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    service_date = date(2026, 8, 12)
    first_batch = store.begin_batch(service_date, "fixture-v1")
    service = _service(service_date, "G1", "A", "B", "08:00", "10:00")
    first_service_id = store.upsert_service(first_batch, service)
    assert store.upsert_service(first_batch, service) == first_service_id
    activated = store.activate_batch(first_batch)
    assert activated.status == "ACTIVE"
    assert activated.service_count == 1
    assert activated.stop_count == 2

    failed_batch = store.begin_batch(service_date, "fixture-v2")
    with pytest.raises(RailTimetableStoreError, match="completeness"):
        store.activate_batch(failed_batch)
    assert store.active_batch(service_date, freshness_hours=48).batch_id == first_batch


def test_batch_cleanup_keeps_active_and_one_previous_success_and_failure(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    service_date = date.today()
    for version in range(3):
        batch_id = store.begin_batch(service_date, f"fixture-v{version}")
        store.upsert_service(batch_id, _service(service_date, "G1", "A", "B", "08:00", "10:00"))
        store.activate_batch(batch_id)
    for version in range(2):
        failed_id = store.begin_batch(service_date, f"failed-v{version}")
        store.fail_batch(failed_id, "fixture failure")

    assert store.cleanup(window_start=service_date, retention_days=45) == 2
    with store.connect_readonly() as conn:
        statuses = [row[0] for row in conn.execute("SELECT status FROM rail_timetable_batch").fetchall()]
    assert statuses.count("ACTIVE") == 1
    assert statuses.count("RETIRED") == 1
    assert statuses.count("FAILED") == 1


def test_store_rejects_non_monotonic_cross_midnight_service(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    service_date = date.today()
    batch_id = store.begin_batch(service_date, "fixture")
    invalid = _service(service_date, "G1", "A", "B", "23:30", "00:30")
    with pytest.raises(RailTimetableStoreError, match="monotonic"):
        store.upsert_service(batch_id, invalid)


def test_local_route_search_direct_direction_transfer_and_cross_midnight(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    service_date = date.today() + timedelta(days=2)
    batch = store.begin_batch(service_date, "fixture")
    store.upsert_service(batch, _service(service_date, "G1", "A", "B", "08:00", "10:00"))
    store.upsert_service(batch, _service(service_date, "D2", "A", "X", "11:00", "12:00"))
    store.upsert_service(batch, _service(service_date, "D3", "X", "B", "13:00", "14:00"))
    store.upsert_service(
        batch,
        _service(service_date, "C4", "A", "Y", "23:30", "00:30", arrival_day_offset=1),
    )
    store.upsert_service(
        batch,
        _service(
            service_date,
            "C5",
            "Y",
            "B",
            "01:30",
            "03:00",
            departure_day_offset=1,
            arrival_day_offset=1,
        ),
    )
    store.activate_batch(batch)
    next_day = service_date + timedelta(days=1)
    next_batch = store.begin_batch(next_day, "fixture")
    store.upsert_service(next_batch, _service(next_day, "G99", "A", "B", "07:00", "09:00"))
    store.activate_batch(next_batch)
    result = RailRouteSearch(store).search(
        service_date=service_date,
        origin_station_codes=("A",),
        destination_station_codes=("B",),
        freshness_hours=48,
        max_candidates=10,
    )
    assert result.snapshot_available is True
    assert result.candidates[0].legs[0].train_number == "G1"
    assert any([leg.train_number for leg in candidate.legs] == ["D2", "D3"] for candidate in result.candidates)
    assert any([leg.train_number for leg in candidate.legs] == ["C4", "C5"] for candidate in result.candidates)
    assert all(candidate.legs[0].train_number != "G99" for candidate in result.candidates)
    assert result.diagnostics.elapsed_ms < 100

    reverse = RailRouteSearch(store).search(
        service_date=service_date,
        origin_station_codes=("B",),
        destination_station_codes=("A",),
        freshness_hours=48,
    )
    assert reverse.candidates == ()


def test_yixing_explicit_station_is_not_truncated_by_hub_rank() -> None:
    candidates = station_candidates_for_location("宜兴", limit=3)
    assert candidates
    assert candidates[0].station_name == "宜兴"
    assert "EXPLICIT_STATION" in candidates[0].ranking_reasons[0]


def test_12306_provider_exact_discovery_and_complete_stops() -> None:
    search_payload = {
        "data": [
            {
                "date": "20260812",
                "from_station": "北京南",
                "station_train_code": "G1",
                "to_station": "上海虹桥",
                "total_num": "2",
                "train_no": "24000000G10L",
            },
            {
                "date": "20260812",
                "from_station": "上海虹桥",
                "station_train_code": "G10",
                "to_station": "北京南",
                "total_num": "2",
                "train_no": "5l00000G1010",
            },
        ]
    }
    detail_payload = {
        "status": True,
        "httpstatus": 200,
        "data": {
            "data": [
                {
                    "station_name": "北京南",
                    "station_train_code": "G1",
                    "station_no": "01",
                    "arrive_time": "----",
                    "start_time": "06:30",
                    "arrive_day_diff": "0",
                },
                {
                    "station_name": "上海虹桥",
                    "station_train_code": "G1",
                    "station_no": "07",
                    "arrive_time": "11:32",
                    "start_time": "11:31",
                    "arrive_day_diff": "0",
                },
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = search_payload if "train/search" in str(request.url) else detail_payload
        return httpx.Response(200, json=payload, headers={"content-type": "application/json"})

    provider = Rail12306TimetableProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), interval_seconds=1)
    provider._wait_for_interval = lambda: None  # type: ignore[method-assign]
    discovered, diagnostics = provider.discover_exact_services(date(2026, 8, 12), ("G1",))
    assert diagnostics.query_count == 1
    assert [item.train_number for item in discovered] == ["G1"]
    service = provider.fetch_complete_service(discovered[0])
    assert service.origin_station_code == "VNP"
    assert service.destination_station_code == "AOH"
    assert len(service.stops) == 2
    assert [stop.stop_sequence for stop in service.stops] == [1, 2]
    assert service.stops[-1].departure_time is None


def test_12306_provider_pauses_on_rate_limit() -> None:
    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(429))),
        interval_seconds=1,
    )
    provider._wait_for_interval = lambda: None  # type: ignore[method-assign]
    with pytest.raises(RailTimetableAccessControlError, match="paused"):
        provider.discover_exact_services(date(2026, 8, 12), ("G1",))


def test_12306_discovery_checkpoint_resumes_after_access_control() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params["keyword"]
        calls.append(keyword)
        if keyword == "D1" and calls.count("D1") == 1:
            return httpx.Response(429)
        train_number = keyword
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "from_station": "北京南",
                        "station_train_code": train_number,
                        "to_station": "上海虹桥",
                        "total_num": "2",
                        "train_no": f"internal_{train_number}",
                    }
                ]
            },
            headers={"content-type": "application/json"},
        )

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        interval_seconds=1,
    )
    provider._wait_for_interval = lambda: None  # type: ignore[method-assign]
    checkpoint: dict[str, object] = {}
    checkpoint_calls = 0

    def save_checkpoint() -> None:
        nonlocal checkpoint_calls
        checkpoint_calls += 1

    with pytest.raises(RailTimetableAccessControlError):
        provider.discover_services(
            date(2026, 8, 12),
            prefixes=("G1", "D1"),
            resume_state=checkpoint,
            checkpoint_callback=save_checkpoint,
        )
    assert checkpoint["pending_prefixes"] == ["D1"]
    assert calls == ["G1", "D1"]

    discovered, diagnostics = provider.discover_services(
        date(2026, 8, 12),
        prefixes=("G1", "D1"),
        resume_state=checkpoint,
        checkpoint_callback=save_checkpoint,
    )
    assert [item.train_number for item in discovered] == ["D1", "G1"]
    assert diagnostics.query_count == 2
    assert calls == ["G1", "D1", "D1"]
    assert checkpoint["status"] == "COMPLETE"
    assert checkpoint_calls >= 3


def test_importer_marks_current_checkpoint_task_paused() -> None:
    checkpoint = {
        "version": 1,
        "dates": {
            "2026-08-12": {
                "status": "PENDING",
                "discovery": {"status": "RUNNING", "pending_prefixes": ["D10"]},
            }
        },
    }

    _mark_checkpoint_paused(checkpoint)

    assert checkpoint["dates"]["2026-08-12"]["status"] == "PAUSED"
    assert checkpoint["dates"]["2026-08-12"]["discovery"]["status"] == "PAUSED"


def test_inventory_verifier_groups_same_station_pair_once() -> None:
    day = date(2026, 8, 12)
    leg_one = _schedule_leg(day, "service_1", "G1", 8)
    leg_two = _schedule_leg(day, "service_2", "G2", 9)
    candidates = (
        _schedule_candidate("candidate_1", leg_one),
        _schedule_candidate("candidate_2", leg_two),
    )
    calls = []

    def search(request, environment):
        calls.append((request, environment))
        return RailProviderSearchResult(
            offers=[_offer(day, "G1", 8), _offer(day, "G2", 9)],
            attempted_source_ids=["fliggy_flyai"],
            outcomes=[RailProviderOutcome("fliggy_flyai", "VERIFIED", None, False, 2, "verified")],
        )

    result = RailInventoryVerifier(search).verify(candidates, max_groups=3)
    assert len(calls) == 1
    assert [item.status for item in result.candidates] == ["AVAILABLE", "AVAILABLE"]
    assert result.diagnostics.external_call_count == 1


def test_inventory_verifier_distinguishes_not_on_sale() -> None:
    day = date(2026, 8, 12)
    candidate = _schedule_candidate("candidate_1", _schedule_leg(day, "service_1", "G1", 8))

    def search(_request, _environment):
        return RailProviderSearchResult(
            offers=[],
            attempted_source_ids=["fliggy_flyai"],
            outcomes=[RailProviderOutcome("fliggy_flyai", "EMPTY", None, False, 0, "not on sale yet")],
        )

    result = RailInventoryVerifier(search).verify((candidate,))
    assert result.candidates[0].status == "NOT_ON_SALE"
    assert result.candidates[0].reason_code == "RAIL_INVENTORY_NOT_ON_SALE"


def test_planner_uses_local_snapshot_and_publishes_only_verified_offer(monkeypatch, tmp_path: Path) -> None:
    day = date.today() + timedelta(days=2)
    database_path = tmp_path / "rail.sqlite3"
    monkeypatch.setenv("TRAVEL_SQLITE_PATH", str(database_path))
    monkeypatch.setenv("TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_RAIL_LOCAL_ROUTING_ENABLED", "true")
    store = RailTimetableStore(database_path)
    batch_id = store.begin_batch(day, "fixture")
    store.upsert_service(batch_id, _service(day, "G1", "VNP", "AOH", "08:00", "12:00"))
    store.activate_batch(batch_id)
    route_nodes = PlanningRouteNodes(
        route_key="北京_上海",
        supported=False,
        city_origin="北京",
        city_destination="上海",
        start_station="北京南",
        end_station="上海虹桥",
        start_airport="",
        end_airport="",
        rail_train="",
        flight_no="",
        station_candidates=(
            _station_candidate("北京南", "北京"),
            _station_candidate("上海虹桥", "上海"),
        ),
        airport_candidates=(),
    )
    monkeypatch.setattr("app.services.planner.planning_nodes_for_request", lambda _origin, _destination: route_nodes)
    monkeypatch.setattr(
        "app.services.planner.resolve_location_city",
        lambda place: "北京" if place == "origin" else "上海",
    )

    verifier_calls: list[tuple[int, int]] = []

    class FixtureVerifier:
        def verify(self, candidates, *, max_groups, **_kwargs):
            verifier_calls.append((len(candidates), max_groups))
            offer = _offer(day, "G1", 8)
            return RailInventoryVerificationResult(
                candidates=(
                    RailInventoryCandidateResult(
                        candidate=candidates[0],
                        status="AVAILABLE",
                        offers=(offer,),
                        reason_code="RAIL_INVENTORY_VERIFIED",
                    ),
                ),
                diagnostics=RailInventoryVerificationDiagnostics(
                    elapsed_ms=1.0,
                    candidate_count=len(candidates),
                    unique_group_count=1,
                    queried_group_count=1,
                    external_call_count=1,
                    budget_exhausted=False,
                    available_count=1,
                    sold_out_count=0,
                    provider_unavailable_count=0,
                ),
            )

    monkeypatch.setattr("app.services.planner.RailInventoryVerifier", FixtureVerifier)
    request = TravelRequest(
        request_id="req_local_snapshot",
        raw_user_input="origin to destination",
        origin_text="origin",
        destination_text="destination",
        travel_date=day,
        preferences=[RecommendationType.BALANCED],
        hard_constraints=TravelHardConstraints(allowed_transport_modes=[TransportMode.RAIL]),
        soft_preferences=TravelSoftPreferences(),
    )

    plans, *_ = build_plans(request)

    local_plans = [plan for plan in plans if plan.plan_id.startswith("plan_rail_local_")]
    assert len(local_plans) == 1
    assert local_plans[0].plan_type == PlanType.DIRECT_RAIL
    assert len(local_plans[0].booking_redirects) == 1
    assert not any(plan.plan_id.startswith("plan_rail_direct_dynamic") for plan in plans)
    assert verifier_calls == [(1, 3)]


def _service(
    service_date: date,
    train_number: str,
    origin_code: str,
    destination_code: str,
    departure_time: str,
    arrival_time: str,
    *,
    departure_day_offset: int = 0,
    arrival_day_offset: int = 0,
) -> RailServiceInput:
    return RailServiceInput(
        service_date=service_date,
        train_no_internal=f"internal_{train_number}",
        train_number=train_number,
        origin_station_code=origin_code,
        destination_station_code=destination_code,
        summary_fingerprint=f"fingerprint_{train_number}",
        fetched_at=datetime.now(tz=UTC),
        stops=(
            RailStopTimeInput(1, origin_code, None, departure_day_offset, departure_time, departure_day_offset),
            RailStopTimeInput(2, destination_code, arrival_time, arrival_day_offset, None, arrival_day_offset),
        ),
    )


def _station_candidate(name: str, city: str) -> StationCandidate:
    return StationCandidate(
        station_id=f"station_{name}",
        station_name=name,
        city_name=city,
        location=GeoPoint(name=name, latitude=30.0, longitude=120.0),
        estimated_transfer_duration_minutes=20,
        estimated_transfer_cost=money(1000, estimated=True),
        ranking_reasons=["fixture"],
        data_source=INTERNAL_LOCATION_SOURCE,
    )


def _schedule_leg(day: date, service_id: str, train_number: str, hour: int) -> RailScheduleLeg:
    return RailScheduleLeg(
        service_id=service_id,
        service_date=day,
        train_no_internal=f"internal_{train_number}",
        train_number=train_number,
        origin_station_code="VNP",
        origin_station_name="北京南",
        destination_station_code="AOH",
        destination_station_name="上海虹桥",
        origin_stop_sequence=1,
        destination_stop_sequence=2,
        departure_at=datetime(day.year, day.month, day.day, hour, tzinfo=SHANGHAI),
        arrival_at=datetime(day.year, day.month, day.day, hour + 4, tzinfo=SHANGHAI),
    )


def _schedule_candidate(candidate_id: str, leg: RailScheduleLeg) -> RailScheduleCandidate:
    return RailScheduleCandidate(
        candidate_id=candidate_id,
        legs=(leg,),
        departure_at=leg.departure_at,
        arrival_at=leg.arrival_at,
        total_duration_minutes=240,
        transfer_station_code=None,
        transfer_station_name=None,
        transfer_wait_minutes=0,
        origin_relevance_rank=0,
        destination_relevance_rank=0,
    )


def _offer(day: date, train_number: str, hour: int) -> RailOffer:
    metadata = rail_data_source_metadata("fliggy_flyai", "Fliggy FlyAI")
    price = money(55000)
    return RailOffer(
        train_number=train_number,
        origin_station="北京南",
        destination_station="上海虹桥",
        departure_at=datetime(day.year, day.month, day.day, hour, tzinfo=SHANGHAI),
        arrival_at=datetime(day.year, day.month, day.day, hour + 4, tzinfo=SHANGHAI),
        duration_minutes=240,
        stop_sequence=["北京南", "上海虹桥"],
        seat_options=[
            SeatOption(
                option_id=f"seat_{train_number}",
                seat_type="二等座",
                price=price,
                availability="AVAILABLE",
                source_option_version=f"fixture_{train_number}",
                data_source=metadata,
            )
        ],
        data_source=metadata,
        origin_station_code="VNP",
        destination_station_code="AOH",
        booking_reference=ProviderBookingReference(
            source_id="fliggy_flyai",
            redirect_url="https://router.feizhu.com/fixture",
            item_fingerprint=f"fingerprint_{train_number}",
            fetched_at=datetime.now(tz=SHANGHAI),
        ),
    )
