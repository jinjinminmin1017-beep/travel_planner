from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.data_sources.config_loader import load_rail_timetable_settings
from app.data_sources.rail_12306_timetable_provider import (
    DiscoveryDiagnostics,
    DiscoveredRailService,
    RailTimetableAccessControlError,
    RailTimetableProviderError,
    RailTimetableTemporaryError,
    RailTimetableUnsupportedStationError,
)
from app.services.rail_timetable_store import RailServiceInput, RailStopTimeInput, RailTimetableStore
from scripts import import_12306_timetable as importer
from scripts.rail_timetable_checkpoint import (
    CheckpointDocument,
    RailCheckpointBusyError,
    atomic_write_json,
    checkpoint_lock,
    manifest_path,
)


DAY = date(2026, 10, 13)
GENERATION = "2026-10-13"


def service(day: date = DAY, number: str = "G1", *, age_hours: int = 0, departure: str = "08:00") -> RailServiceInput:
    return RailServiceInput(
        service_date=day, train_no_internal=f"internal_{number}", train_number=number,
        origin_station_code="VNP", destination_station_code="AOH", summary_fingerprint=f"fp_{number}",
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=age_hours),
        stops=(RailStopTimeInput(1, "VNP", None, 0, departure, 0), RailStopTimeInput(2, "AOH", "12:00", 0, None, 0)),
    )


def discovery_row(value: RailServiceInput) -> dict[str, object]:
    return {
        "train_no_internal": value.train_no_internal, "train_number": value.train_number,
        "origin_station_name": "北京南", "destination_station_name": "上海虹桥",
        "total_stop_count": 2, "summary_fingerprint": value.summary_fingerprint,
    }


class FixtureProvider:
    def __init__(self, services: list[RailServiceInput], *, failures: dict[str, BaseException] | None = None) -> None:
        self.services = services
        self.failures = failures or {}
        self.detail_calls: list[str] = []
        self.discovery_inputs: list[dict[str, object]] = []
        self.discovery_calls: list[date] = []
        self.request_metrics = {"requests": 0, "network_seconds": 0.0, "discovery_requests": 0, "detail_requests": 0}

    def discover_services(self, day, *, resume_state, checkpoint_callback, **_kwargs):
        self.discovery_calls.append(day)
        self.discovery_inputs.append(dict(resume_state))
        values = [value for value in self.services if value.service_date == day]
        resume_state.update({"status": "COMPLETE", "pending_prefixes": [], "services": {
            value.train_no_internal: discovery_row(value) for value in values
        }, "query_count": 1})
        checkpoint_callback()
        discovered = [DiscoveredRailService(day, value.train_no_internal, value.train_number, "北京南", "上海虹桥", 2, value.summary_fingerprint) for value in values]
        return discovered, DiscoveryDiagnostics(1, 0, len(discovered), ())

    def fetch_complete_service(self, discovered):
        self.detail_calls.append(discovered.train_no_internal)
        failure = self.failures.pop(discovered.train_no_internal, None)
        if failure:
            raise failure
        return next(value for value in self.services if value.service_date == discovered.service_date and value.train_no_internal == discovered.train_no_internal)


def run_date(tmp_path: Path, store: RailTimetableStore, provider: FixtureProvider, checkpoint: CheckpointDocument, **kwargs):
    return importer._import_date(
        service_date=DAY, provider=provider, store=store, checkpoint=checkpoint,
        checkpoint_path=tmp_path / "checkpoint.json", resume=True, dry_run=False,
        train_numbers=(), prefixes=("G", "D", "C"), max_discovery_queries=None,
        max_trains=None, refresh=True, generation=GENERATION, **kwargs,
    )


def test_v1_migration_preserves_original_and_keeps_manifest_small(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    original = {"version": 1, "dates": {DAY.isoformat(): {
        "batch_id": "old_batch", "status": "STAGING", "completed_train_nos": ["internal_G1"],
        "discovery": {"services": {"internal_G1": discovery_row(service())}},
    }}}
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_bytes()
    document = CheckpointDocument(path, resume=True)
    assert document.date_state(DAY.isoformat())["batch_id"] == "old_batch"
    document.save_date(DAY.isoformat())

    manifest = json.loads(manifest_path(path).read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert "discovery" not in manifest["dates"][DAY.isoformat()]
    assert "completed_train_nos" not in manifest["dates"][DAY.isoformat()]
    assert path.read_bytes() == before
    assert CheckpointDocument(path, resume=True).date_state(DAY.isoformat())["batch_id"] == "old_batch"


def test_date_file_recovers_when_process_stops_before_manifest_write(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    document = CheckpointDocument(path, resume=False)
    document.date_state(DAY.isoformat()).update({"batch_id": "committed_batch", "status": "STAGING"})
    real_write = document._write

    def fail_manifest(target, payload):
        if target == document.path:
            raise OSError("simulated power loss before publishing manifest")
        real_write(target, payload)

    monkeypatch.setattr(document, "_write", fail_manifest)
    with pytest.raises(OSError):
        document.save_date(DAY.isoformat())
    recovered = CheckpointDocument(path, resume=True)
    assert recovered.date_state(DAY.isoformat())["batch_id"] == "committed_batch"


def test_legacy_migration_never_overwrites_newer_orphan_date_state(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"version": 1, "dates": {DAY.isoformat(): {"batch_id": "legacy_batch", "status": "FAILED"}}}), encoding="utf-8")
    document = CheckpointDocument(path, resume=True)
    date_path = document.directory / f"{DAY.isoformat()}.json"
    atomic_write_json(date_path, {"version": 2, "service_date": DAY.isoformat(), "state": {"batch_id": "new_batch", "status": "STAGING"}})
    document.save_manifest()
    assert CheckpointDocument(path, resume=True).date_state(DAY.isoformat())["batch_id"] == "new_batch"
    assert json.loads(date_path.read_text(encoding="utf-8"))["state"]["batch_id"] == "new_batch"


def test_database_commits_ahead_of_checkpoint_resume_without_refetch(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch = store.begin_batch(DAY, "fixture")
    store.upsert_service(batch, service())
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({"batch_id": batch, "status": "STAGING", "generation": GENERATION, "completed_train_nos": []})
    checkpoint.save_date(DAY.isoformat())
    provider = FixtureProvider([service(), service(number="G2")])
    summary = run_date(tmp_path, store, provider, CheckpointDocument(tmp_path / "checkpoint.json", resume=True))
    assert provider.detail_calls == ["internal_G2"]
    assert summary["service_count"] == 2
    assert summary["metrics"]["resumed_count"] == 1
    assert store.active_batch(DAY, freshness_hours=None).batch_id == batch


def test_checkpoint_completion_cannot_claim_uncommitted_service(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch = store.begin_batch(DAY, "fixture")
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({"batch_id": batch, "status": "STAGING", "generation": GENERATION, "completed_train_nos": ["internal_G1"]})
    provider = FixtureProvider([service()])
    summary = run_date(tmp_path, store, provider, checkpoint)
    assert provider.detail_calls == ["internal_G1"]
    assert summary["service_count"] == 1


def test_new_generation_rediscovers_and_reuses_only_still_present_rows(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    old_batch = store.begin_batch(DAY, "fixture")
    store.upsert_services(old_batch, [service(), service(number="G3")])
    store.fail_batch(old_batch, "fixture failure")
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({
        "batch_id": old_batch, "status": "FAILED", "generation": "2026-10-12",
        "discovery": {"status": "COMPLETE", "pending_prefixes": [], "services": {"internal_G3": discovery_row(service(number="G3"))}},
    })
    provider = FixtureProvider([service(), service(number="G2")])
    summary = run_date(tmp_path, store, provider, checkpoint)
    active = store.active_batch(DAY, freshness_hours=None)
    assert provider.discovery_inputs == [{}]
    assert provider.detail_calls == ["internal_G2"]
    assert active.batch_id != old_batch
    assert set(store.batch_service_progress(active.batch_id)) == {"internal_G1", "internal_G2"}
    assert store.get_batch(old_batch) is not None
    assert summary["metrics"]["reused_count"] == 1


def test_unchanged_summary_rechecks_expired_full_times_and_same_day_repeat_skips(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    old_batch = store.begin_batch(DAY, "fixture")
    store.upsert_service(old_batch, service(age_hours=48))
    store.activate_batch(old_batch)
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({"batch_id": old_batch, "generation": "2026-10-12", "status": "ACTIVE"})
    provider = FixtureProvider([service(departure="09:00")])
    summary = run_date(tmp_path, store, provider, checkpoint, detail_ttl_hours=36)
    assert provider.detail_calls == ["internal_G1"]
    assert summary["metrics"]["reused_count"] == 0
    active = store.active_batch(DAY, freshness_hours=None)
    with store.connect_readonly() as connection:
        departure = connection.execute("SELECT departure_time FROM rail_stop_time stop JOIN rail_service service ON service.service_id=stop.service_id WHERE service.batch_id=? AND stop.stop_sequence=1", (active.batch_id,)).fetchone()[0]
    assert departure == "09:00"
    repeated = FixtureProvider([service(departure="09:00")])
    again = run_date(tmp_path, store, repeated, checkpoint)
    assert again["already_active"]
    assert repeated.discovery_calls == []
    assert repeated.detail_calls == []


def test_same_generation_expired_staging_row_removed_when_detail_is_quarantined(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    staging = store.begin_batch(DAY, "fixture")
    store.upsert_services(staging, [service(age_hours=48), service(number="G2")])
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({"batch_id": staging, "generation": GENERATION, "status": "STAGING"})
    provider = FixtureProvider([service(), service(number="G2")], failures={"internal_G1": RailTimetableUnsupportedStationError("fixture_station")})
    result = run_date(tmp_path, store, provider, checkpoint)
    assert result["activated"]
    assert result["service_count"] == 1
    assert set(store.batch_service_progress(staging)) == {"internal_G2"}
    assert checkpoint.date_state(DAY.isoformat())["discovery"]["quarantined_services"]["internal_G1"]["reason"] == "UNSUPPORTED_STATION"


def test_failed_batch_resume_prunes_services_no_longer_in_discovery(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    failed = store.begin_batch(DAY, "fixture")
    store.upsert_services(failed, [service(), service(number="G2")])
    store.fail_batch(failed, "quarantine state committed before process stopped")
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    checkpoint.date_state(DAY.isoformat()).update({"batch_id": failed, "generation": GENERATION, "status": "FAILED"})
    provider = FixtureProvider([service(number="G2")])
    result = run_date(tmp_path, store, provider, checkpoint)
    active = store.active_batch(DAY, freshness_hours=None)
    assert result["activated"]
    assert result["service_count"] == 1
    assert set(store.batch_service_progress(active.batch_id)) == {"internal_G2"}
    assert set(store.batch_service_progress(failed)) == {"internal_G1", "internal_G2"}
    assert provider.detail_calls == []


def test_budget_flushes_validated_buffer_but_never_activates_incomplete_date(monkeypatch, tmp_path: Path) -> None:
    clock = [0.0]
    monkeypatch.setattr(importer.time, "monotonic", lambda: clock[0])
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)

    class SlowProvider(FixtureProvider):
        def fetch_complete_service(self, discovered):
            value = super().fetch_complete_service(discovered)
            clock[0] += 6
            return value

    provider = SlowProvider([service(), service(number="G2")])
    result = run_date(tmp_path, store, provider, checkpoint, budget=importer.ImportBudget(date_seconds=5))
    state = checkpoint.date_state(DAY.isoformat())
    assert result["budget_exhausted"]
    assert state["status"] == "STAGING"
    assert store.active_batch(DAY, freshness_hours=None) is None
    assert set(store.batch_service_progress(state["batch_id"])) == {"internal_G1"}
    resumed = FixtureProvider([service(), service(number="G2")])
    assert run_date(tmp_path, store, resumed, CheckpointDocument(tmp_path / "checkpoint.json", resume=True))["activated"]
    assert resumed.detail_calls == ["internal_G2"]


def test_keyboard_interrupt_flushes_and_saves_resumable_progress(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    provider = FixtureProvider([service(), service(number="G2")], failures={"internal_G2": KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        run_date(tmp_path, store, provider, checkpoint)
    recovered = CheckpointDocument(tmp_path / "checkpoint.json", resume=True).date_state(DAY.isoformat())
    assert recovered["status"] == "PAUSED"
    assert set(store.batch_service_progress(recovered["batch_id"])) == {"internal_G1"}
    assert store.active_batch(DAY, freshness_hours=None) is None


def arguments(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        checkpoint=tmp_path / "checkpoint.json", resume=True, interval_seconds=1.5,
        date_from=DAY, days=3, mode="refresh", dry_run=False, train_number=[], prefix=[],
        max_discovery_queries=None, max_trains=None, _generation=GENERATION,
    )


@pytest.mark.parametrize("failure, expected_exit", [
    (RailTimetableProviderError("bad discovery schema"), importer.EXIT_FAILED),
    (RailTimetableTemporaryError("temporary discovery failure"), importer.EXIT_TRANSIENT_FAILURE),
])
def test_date_failure_isolated_and_later_dates_complete(monkeypatch, tmp_path: Path, failure, expected_exit) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    values = [service(DAY + timedelta(days=offset)) for offset in range(3)]

    class FailingDateProvider(FixtureProvider):
        def discover_services(self, day, **kwargs):
            if day == DAY:
                raise failure
            return super().discover_services(day, **kwargs)

    provider = FailingDateProvider(values)
    monkeypatch.setattr(importer, "Rail12306TimetableProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(importer, "RailTimetableStore", lambda: store)
    assert importer._run_import_once(arguments(tmp_path), load_rail_timetable_settings({})) == expected_exit
    for offset in (1, 2):
        assert store.active_batch(DAY + timedelta(days=offset), freshness_hours=None) is not None
    failed = CheckpointDocument(tmp_path / "checkpoint.json", resume=True).date_state(DAY.isoformat())
    assert failed["status"] == "FAILED"


def test_access_control_stops_globally_and_persists_discovery_pause(monkeypatch, tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")

    class PausedProvider(FixtureProvider):
        def discover_services(self, day, **kwargs):
            self.discovery_calls.append(day)
            raise RailTimetableAccessControlError("access challenge")

    provider = PausedProvider([])
    monkeypatch.setattr(importer, "Rail12306TimetableProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(importer, "RailTimetableStore", lambda: store)
    monkeypatch.setattr(store, "cleanup", lambda **_kwargs: pytest.fail("access control must not run cleanup"))
    assert importer._run_import_once(arguments(tmp_path), load_rail_timetable_settings({})) == importer.EXIT_ACCESS_CONTROL
    assert provider.discovery_calls == [DAY]
    assert CheckpointDocument(tmp_path / "checkpoint.json", resume=True).date_state(DAY.isoformat())["status"] == "PAUSED"


def test_sqlite_system_failure_stops_other_dates(monkeypatch, tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    provider = FixtureProvider([service(DAY + timedelta(days=offset)) for offset in range(3)])
    monkeypatch.setattr(importer, "Rail12306TimetableProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(importer, "RailTimetableStore", lambda: store)

    def storage_failure(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(store, "begin_batch", storage_failure)
    with pytest.raises(sqlite3.OperationalError):
        importer._run_import_once(arguments(tmp_path), load_rail_timetable_settings({}))
    assert provider.discovery_calls == [DAY]


def test_transient_resume_keeps_other_completed_dates_and_refresh_generation(monkeypatch, tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    values = [service(DAY + timedelta(days=offset)) for offset in range(3)]
    failed_once = [False]
    providers = []

    class OneTransientFailure(FixtureProvider):
        def discover_services(self, day, **kwargs):
            if day == DAY and not failed_once[0]:
                failed_once[0] = True
                raise RailTimetableTemporaryError("temporary discovery failure")
            return super().discover_services(day, **kwargs)

    def create_provider(**_kwargs):
        provider = OneTransientFailure(values)
        providers.append(provider)
        return provider

    monkeypatch.setattr(importer, "Rail12306TimetableProvider", create_provider)
    monkeypatch.setattr(importer, "RailTimetableStore", lambda: store)
    args = arguments(tmp_path)
    settings = load_rail_timetable_settings({})
    assert importer._run_import_once(args, settings) == importer.EXIT_TRANSIENT_FAILURE
    completed_before = [store.active_batch(DAY + timedelta(days=offset), freshness_hours=None).batch_id for offset in (1, 2)]
    assert importer._run_import_once(args, settings) == 0
    assert providers[1].discovery_calls == [DAY]
    assert completed_before == [store.active_batch(DAY + timedelta(days=offset), freshness_hours=None).batch_id for offset in (1, 2)]


def test_checkpoint_writes_are_bounded_by_cadence_and_phase_boundaries(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    values = [service(number=f"G{index + 1}") for index in range(250)]
    checkpoint = CheckpointDocument(tmp_path / "checkpoint.json", resume=False)
    provider = FixtureProvider(values)
    result = run_date(tmp_path, store, provider, checkpoint, checkpoint_every=100,
                      checkpoint_interval=3600, storage_batch_size=50)
    assert result["activated"]
    assert result["metrics"]["checkpoint_writes"] <= 14
    assert result["metrics"]["checkpoint_bytes"] < 400_000
    assert result["metrics"]["fetched_count"] == 250


def test_missing_manifest_date_file_is_not_silently_reset(tmp_path: Path) -> None:
    from scripts.rail_timetable_checkpoint import RailCheckpointError
    path = tmp_path / "checkpoint.json"
    atomic_write_json(manifest_path(path), {"version": 2, "dates": {DAY.isoformat(): {
        "state_file": f"{DAY.isoformat()}.json", "batch_id": "existing_batch",
    }}})
    with pytest.raises(RailCheckpointError, match="missing date file"):
        CheckpointDocument(path, resume=True).date_state(DAY.isoformat())


def test_date_order_prioritizes_near_gap_reserves_tail_and_ages_deferred_work(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    dates = [DAY + timedelta(days=offset) for offset in range(4)]
    assert importer._ordered_dates(dates, store, {"dates": {}}, 36) == [dates[0], dates[3], dates[1], dates[2]]
    checkpoint = {"dates": {dates[2].isoformat(): {"deferred_runs": 2}}}
    assert importer._ordered_dates(dates, store, checkpoint, 36)[0] == dates[2]


def test_supervisor_shared_budget_caps_retry_wait_and_stops(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(importer.time, "monotonic", lambda: clock[0])
    delays = []
    calls = []

    def run_once():
        calls.append(1)
        clock[0] += 2
        return importer.EXIT_TRANSIENT_FAILURE

    def sleep(seconds):
        delays.append(seconds)
        clock[0] += seconds

    result = importer._run_with_transient_resume(run_once, enabled=True, max_resumes=6,
        base_delay_seconds=300, max_delay_seconds=3600, sleep=sleep, deadline=10)
    assert result == importer.EXIT_BUDGET_EXHAUSTED
    assert delays == [8]
    assert len(calls) == 1


def test_checkpoint_lock_rejects_second_writer_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    with checkpoint_lock(path):
        with pytest.raises(RailCheckpointBusyError):
            with checkpoint_lock(path):
                pytest.fail("second writer acquired the lock")
    with checkpoint_lock(path):
        pass
