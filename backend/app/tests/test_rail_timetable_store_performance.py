from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.services.rail_timetable_store as store_module
from app.services.rail_timetable_store import (
    RailServiceInput,
    RailStopTimeInput,
    RailTimetableStore,
    RailTimetableStoreError,
)


SERVICE_DATE = date(2026, 10, 20)
FETCHED_AT = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def _service(train_number: str, stop_count: int = 2) -> RailServiceInput:
    stops = []
    for index in range(stop_count):
        clock = (datetime(2026, 1, 1, 8) + timedelta(minutes=index * 30)).strftime("%H:%M")
        stops.append(
            RailStopTimeInput(
                stop_sequence=index + 1,
                station_code="A" if index == 0 else "B" if index == stop_count - 1 else f"I{index}",
                arrival_time=clock if index else None,
                arrival_day_offset=0,
                departure_time=clock if index < stop_count - 1 else None,
                departure_day_offset=0,
            )
        )
    return RailServiceInput(
        service_date=SERVICE_DATE,
        train_no_internal=f"internal-{train_number}",
        train_number=train_number,
        origin_station_code="A",
        destination_station_code="B",
        summary_fingerprint=f"{train_number}-{stop_count}",
        fetched_at=FETCHED_AT,
        stops=tuple(stops),
    )


def _assert_counts(store: RailTimetableStore, batch_id: str, services: int, stops: int) -> None:
    batch = store.get_batch(batch_id)
    assert batch is not None
    assert (batch.service_count, batch.stop_count) == (services, stops)
    with sqlite3.connect(store.path) as conn:
        actual_services = conn.execute(
            "SELECT COUNT(*) FROM rail_service WHERE batch_id = ?", (batch_id,)
        ).fetchone()[0]
        actual_stops = conn.execute(
            "SELECT COUNT(*) FROM rail_stop_time stop JOIN rail_service service USING(service_id) "
            "WHERE service.batch_id = ?", (batch_id,)
        ).fetchone()[0]
    assert (actual_services, actual_stops) == (services, stops)


def _trace_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    statements: list[str] = []
    original = store_module._connect

    def traced(path: Path) -> sqlite3.Connection:
        conn = original(path)
        conn.set_trace_callback(lambda sql: statements.append(" ".join(sql.upper().split())))
        return conn

    monkeypatch.setattr(store_module, "_connect", traced)
    return statements


def test_single_upsert_counts_remain_exact_when_stop_count_changes(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    service_id = store.upsert_service(batch_id, _service("G1"))
    assert store.upsert_service(batch_id, _service("G1")) == service_id
    _assert_counts(store, batch_id, 1, 2)
    assert store.upsert_service(batch_id, _service("G1", 4)) == service_id
    _assert_counts(store, batch_id, 1, 4)
    store.upsert_service(batch_id, _service("G2", 3))
    store.upsert_service(batch_id, _service("G1", 2))
    _assert_counts(store, batch_id, 2, 5)


def test_batch_upsert_uses_one_transaction_without_whole_batch_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    statements = _trace_connections(monkeypatch)
    service_ids = store.upsert_services(
        batch_id, [_service(f"G{index}") for index in range(1, 101)] + [_service("G1", 3)]
    )
    assert len(service_ids) == 101 and service_ids[0] == service_ids[-1]
    assert sum(sql == "BEGIN IMMEDIATE" for sql in statements) == 1
    assert sum(sql == "COMMIT" for sql in statements) == 1
    assert not any("COUNT(" in sql for sql in statements)
    _assert_counts(store, batch_id, 100, 201)


def test_single_upserts_do_not_recount_entire_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    statements = _trace_connections(monkeypatch)
    for index in range(1, 21):
        store.upsert_service(batch_id, _service(f"G{index}"))
    assert not any("COUNT(" in sql for sql in statements)
    _assert_counts(store, batch_id, 20, 40)


def test_batch_sql_failure_rolls_back_overwrite_new_services_and_counters(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    store.upsert_service(batch_id, _service("G1"))
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_fixture_stop BEFORE INSERT ON rail_stop_time "
            "WHEN NEW.station_code = 'BLOCK' BEGIN SELECT RAISE(ABORT, 'fixture rejected'); END"
        )
    second = _service("G2")
    second = replace(second, stops=(replace(second.stops[0], station_code="BLOCK"), second.stops[1]))
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejected"):
        store.upsert_services(batch_id, [_service("G1", 4), second])
    _assert_counts(store, batch_id, 1, 2)
    progress = store.batch_service_progress(batch_id)
    assert set(progress) == {"internal-G1"}
    assert progress["internal-G1"].summary_fingerprint == "G1-2"


def test_batch_date_mismatch_rolls_back_prior_service_writes(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    wrong_date = replace(_service("G2"), service_date=SERVICE_DATE + timedelta(days=1))
    with pytest.raises(RailTimetableStoreError, match="date does not match"):
        store.upsert_services(batch_id, [_service("G1"), wrong_date])
    _assert_counts(store, batch_id, 0, 0)
    assert store.batch_service_progress(batch_id) == {}


def test_progress_after_restart_contains_only_committed_chunks_and_utc_fetch_times(tmp_path: Path) -> None:
    path = tmp_path / "rail.sqlite3"
    store = RailTimetableStore(path)
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    local_time = FETCHED_AT.astimezone(timezone(timedelta(hours=8)))
    store.upsert_services(batch_id, [_service("G1"), replace(_service("G2"), fetched_at=local_time)])
    invalid = replace(_service("G4"), stops=(_service("G4").stops[0],))
    with pytest.raises(RailTimetableStoreError, match="at least two"):
        store.upsert_services(batch_id, [_service("G3"), invalid])
    reopened = RailTimetableStore(path)
    progress = reopened.batch_service_progress(batch_id)
    assert set(progress) == {"internal-G1", "internal-G2"}
    assert progress["internal-G2"].summary_fingerprint == "G2-2"
    assert progress["internal-G2"].fetched_at == FETCHED_AT
    assert progress["internal-G2"].fetched_at.tzinfo == timezone.utc
    reopened.upsert_services(batch_id, [_service("G3"), _service("G4")])
    _assert_counts(reopened, batch_id, 4, 8)


def test_copy_across_sql_chunks_recounts_once_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    source = store.begin_batch(SERVICE_DATE, "source")
    services = [_service(f"G{index}") for index in range(1, 502)]
    store.upsert_services(source, services)
    store.activate_batch(source)
    target = store.begin_batch(SERVICE_DATE, "target")
    store.upsert_services(target, [_service("G1", 4), _service("G999", 3)])
    requested = [service.train_no_internal for service in services] + ["missing", "internal-G1"]
    statements = _trace_connections(monkeypatch)
    copied = store.copy_services(source, target, requested)
    assert copied == {service.train_no_internal for service in services}
    count_statements = [sql for sql in statements if "COUNT(" in sql]
    assert len(count_statements) == 2
    assert sum(sql == "BEGIN IMMEDIATE" for sql in statements) == 1
    assert sum(sql == "COMMIT" for sql in statements) == 1
    _assert_counts(store, target, 502, 1005)
    store.copy_services(source, target, requested)
    _assert_counts(store, target, 502, 1005)
    progress = store.batch_service_progress(target)
    assert progress["internal-G1"].summary_fingerprint == "G1-2"
    assert progress["internal-G1"].fetched_at == FETCHED_AT


def test_copy_sql_failure_preserves_existing_target_rows_and_counts(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    source = store.begin_batch(SERVICE_DATE, "source")
    store.upsert_services(source, [_service("G1"), _service("G2")])
    target = store.begin_batch(SERVICE_DATE, "target")
    store.upsert_service(target, _service("G1", 4))
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_fixture_copy BEFORE INSERT ON rail_service "
            "WHEN NEW.batch_id = '" + target + "' AND NEW.train_number = 'G2' "
            "BEGIN SELECT RAISE(ABORT, 'copy rejected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="copy rejected"):
        store.copy_services(source, target, ["internal-G1", "internal-G2"])
    _assert_counts(store, target, 1, 4)
    assert store.batch_service_progress(target)["internal-G1"].summary_fingerprint == "G1-4"


def test_self_copy_keeps_stops(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    store.upsert_service(batch_id, _service("G1", 3))
    assert store.copy_services(batch_id, batch_id, ["internal-G1", "missing"]) == {"internal-G1"}
    _assert_counts(store, batch_id, 1, 3)


def test_activation_recounts_actual_rows_and_blocks_incomplete_replacement(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    active = store.begin_batch(SERVICE_DATE, "active")
    store.upsert_service(active, _service("G1"))
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE rail_timetable_batch SET service_count=90, stop_count=180 WHERE batch_id=?", (active,)
        )
    result = store.activate_batch(active)
    assert (result.service_count, result.stop_count) == (1, 2)
    replacement = store.begin_batch(SERVICE_DATE, "replacement")
    service_id = store.upsert_service(replacement, _service("G2"))
    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM rail_stop_time WHERE service_id=? AND stop_sequence=2", (service_id,))
    with pytest.raises(RailTimetableStoreError, match="completeness gate"):
        store.activate_batch(replacement)
    assert store.get_batch(active).status == "ACTIVE"
    assert store.get_batch(replacement).status == "STAGING"
    with pytest.raises(RailTimetableStoreError, match="STAGING"):
        store.upsert_service(active, _service("G3"))


def test_concurrent_batches_of_upserts_keep_shared_service_counters_exact(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")

    def write_chunk(worker: int) -> None:
        services = [_service(f"G{1000 * (worker + 1) + index}") for index in range(20)]
        services.append(_service("G1", worker + 2))
        store.upsert_services(batch_id, services)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_chunk, range(4)))
    batch = store.get_batch(batch_id)
    assert batch is not None and batch.service_count == 81
    assert 162 <= batch.stop_count <= 165
    _assert_counts(store, batch_id, 81, batch.stop_count)


def test_delete_services_is_scoped_idempotent_and_counts_changed_stops(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    first = store.begin_batch(SERVICE_DATE, "first")
    second = store.begin_batch(SERVICE_DATE, "second")
    store.upsert_services(first, [_service("G1", 3), _service("G2", 4)])
    store.upsert_service(second, _service("G1", 5))
    assert store.delete_services(first, ["missing"]) == 0
    _assert_counts(store, first, 2, 7)
    assert store.delete_services(first, iter(["internal-G1", "internal-G1", "missing"])) == 1
    _assert_counts(store, first, 1, 4)
    _assert_counts(store, second, 1, 5)
    assert store.delete_services(first, ["internal-G1"]) == 0
    assert store.delete_services(first, ["internal-G2"]) == 1
    _assert_counts(store, first, 0, 0)
    assert store.batch_service_progress(first) == {}


def test_delete_services_rejects_active_batch_without_mutating_it(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    store.upsert_service(batch_id, _service("G1", 3))
    store.activate_batch(batch_id)
    with pytest.raises(RailTimetableStoreError, match="STAGING"):
        store.delete_services(batch_id, ["internal-G1"])
    _assert_counts(store, batch_id, 1, 3)
    assert store.get_batch(batch_id).status == "ACTIVE"
    with pytest.raises(RailTimetableStoreError, match="STAGING"):
        store.delete_services("unknown-batch", ["internal-G1"])


def test_delete_services_sql_failure_rolls_back_stops_rows_and_counters(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    store.upsert_services(batch_id, [_service("G1", 3), _service("G2", 4)])
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_fixture_delete BEFORE DELETE ON rail_service "
            "WHEN OLD.train_number = 'G2' BEGIN SELECT RAISE(ABORT, 'delete rejected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="delete rejected"):
        store.delete_services(batch_id, ["internal-G1", "internal-G2"])
    _assert_counts(store, batch_id, 2, 7)
    assert set(store.batch_service_progress(batch_id)) == {"internal-G1", "internal-G2"}


def test_delete_services_across_sql_chunks_uses_one_transaction_and_no_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    batch_id = store.begin_batch(SERVICE_DATE, "fixture")
    store.upsert_services(batch_id, [_service(f"G{index}") for index in range(1, 602)])
    statements = _trace_connections(monkeypatch)
    requested = [f"internal-G{index}" for index in range(1, 506)] + ["missing", "internal-G1"]
    assert store.delete_services(batch_id, requested) == 505
    assert sum(sql == "BEGIN IMMEDIATE" for sql in statements) == 1
    assert sum(sql == "COMMIT" for sql in statements) == 1
    assert not any("COUNT(" in sql for sql in statements)
    _assert_counts(store, batch_id, 96, 192)


def test_store_connection_commits_closes_and_releases_file_without_gc(tmp_path: Path) -> None:
    path = tmp_path / "connection.sqlite3"
    connection = store_module._connect(path)
    assert isinstance(connection, sqlite3.Connection)
    with connection:
        connection.execute("CREATE TABLE fixture(value INTEGER)")
        connection.execute("INSERT INTO fixture(value) VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    observer = sqlite3.connect(path)
    try:
        assert observer.execute("SELECT value FROM fixture").fetchone() == (1,)
    finally:
        observer.close()
    # The closed connection object remains referenced while Windows unlinks its DB.
    path.unlink()
    assert not path.exists()


def test_store_connection_rolls_back_closes_and_propagates_original_exception(tmp_path: Path) -> None:
    path = tmp_path / "connection.sqlite3"
    connection = store_module._connect(path)
    original_error = RuntimeError("fixture work failed")
    with pytest.raises(RuntimeError, match="fixture work failed") as raised:
        with connection:
            connection.execute("CREATE TABLE fixture(value INTEGER)")
            connection.execute("INSERT INTO fixture(value) VALUES (1)")
            raise original_error
    assert raised.value is original_error
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    observer = sqlite3.connect(path)
    try:
        assert observer.execute("SELECT COUNT(*) FROM fixture").fetchone() == (0,)
    finally:
        observer.close()


def test_store_connection_commit_failure_also_closes_and_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "connection.sqlite3"
    connection = store_module._connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        with connection:
            connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
            )
            connection.execute("INSERT INTO child(parent_id) VALUES (999)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    observer = sqlite3.connect(path)
    try:
        assert observer.execute("SELECT COUNT(*) FROM child").fetchone() == (0,)
    finally:
        observer.close()


def test_readonly_connection_closes_at_context_exit(tmp_path: Path) -> None:
    store = RailTimetableStore(tmp_path / "rail.sqlite3")
    connection = store.connect_readonly()
    with connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
