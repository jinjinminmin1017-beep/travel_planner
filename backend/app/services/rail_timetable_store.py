from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Sequence
from uuid import uuid4


BatchStatus = Literal["STAGING", "ACTIVE", "FAILED", "RETIRED"]
DEFAULT_DB_PATH = Path("logs/travel_planner.sqlite3")


@dataclass(frozen=True)
class RailStopTimeInput:
    stop_sequence: int
    station_code: str
    arrival_time: str | None
    arrival_day_offset: int
    departure_time: str | None
    departure_day_offset: int


@dataclass(frozen=True)
class RailServiceInput:
    service_date: date
    train_no_internal: str
    train_number: str
    origin_station_code: str
    destination_station_code: str
    summary_fingerprint: str
    fetched_at: datetime
    stops: tuple[RailStopTimeInput, ...]


@dataclass(frozen=True)
class RailTimetableBatch:
    batch_id: str
    service_date: date
    status: BatchStatus
    source_version: str
    started_at: datetime
    completed_at: datetime | None
    service_count: int
    stop_count: int
    error_count: int
    last_error: str | None


@dataclass(frozen=True)
class RailTimetableCoverage:
    service_date: date
    status: BatchStatus
    completed_at: datetime | None
    service_count: int
    stop_count: int
    fresh: bool


class RailTimetableStoreError(RuntimeError):
    pass


def rail_timetable_database_path() -> Path:
    return Path(os.getenv("TRAVEL_SQLITE_PATH", str(DEFAULT_DB_PATH)))


def ensure_rail_timetable_schema(path: Path | None = None) -> None:
    database_path = path or rail_timetable_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rail_timetable_batch (
              batch_id TEXT PRIMARY KEY,
              service_date TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('STAGING', 'ACTIVE', 'FAILED', 'RETIRED')),
              source_version TEXT NOT NULL,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              service_count INTEGER NOT NULL DEFAULT 0 CHECK (service_count >= 0),
              stop_count INTEGER NOT NULL DEFAULT 0 CHECK (stop_count >= 0),
              error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
              last_error TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_rail_timetable_active_date
              ON rail_timetable_batch(service_date) WHERE status = 'ACTIVE';
            CREATE INDEX IF NOT EXISTS ix_rail_timetable_batch_date_status
              ON rail_timetable_batch(service_date, status, completed_at);

            CREATE TABLE IF NOT EXISTS rail_service (
              service_id TEXT PRIMARY KEY,
              batch_id TEXT NOT NULL REFERENCES rail_timetable_batch(batch_id) ON DELETE CASCADE,
              service_date TEXT NOT NULL,
              train_no_internal TEXT NOT NULL,
              train_number TEXT NOT NULL,
              origin_station_code TEXT NOT NULL,
              destination_station_code TEXT NOT NULL,
              summary_fingerprint TEXT NOT NULL,
              fetched_at TEXT NOT NULL,
              UNIQUE(batch_id, train_no_internal)
            );

            CREATE INDEX IF NOT EXISTS ix_rail_service_batch_date_train
              ON rail_service(batch_id, service_date, train_number);
            CREATE INDEX IF NOT EXISTS ix_rail_service_date_train
              ON rail_service(service_date, train_number);

            CREATE TABLE IF NOT EXISTS rail_stop_time (
              service_id TEXT NOT NULL REFERENCES rail_service(service_id) ON DELETE CASCADE,
              stop_sequence INTEGER NOT NULL CHECK (stop_sequence >= 1),
              station_code TEXT NOT NULL,
              arrival_time TEXT,
              arrival_day_offset INTEGER NOT NULL CHECK (arrival_day_offset >= 0),
              departure_time TEXT,
              departure_day_offset INTEGER NOT NULL CHECK (departure_day_offset >= 0),
              PRIMARY KEY(service_id, stop_sequence)
            );

            CREATE INDEX IF NOT EXISTS ix_rail_stop_service_sequence
              ON rail_stop_time(service_id, stop_sequence);
            CREATE INDEX IF NOT EXISTS ix_rail_stop_station_service
              ON rail_stop_time(station_code, service_id, stop_sequence);
            """
        )


class RailTimetableStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or rail_timetable_database_path()
        ensure_rail_timetable_schema(self.path)

    def begin_batch(self, service_date: date, source_version: str, *, batch_id: str | None = None) -> str:
        value = batch_id or f"rail_{service_date.isoformat()}_{uuid4().hex[:12]}"
        now = _utc_now()
        with _connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO rail_timetable_batch(
                  batch_id, service_date, status, source_version, started_at,
                  completed_at, service_count, stop_count, error_count, last_error
                ) VALUES (?, ?, 'STAGING', ?, ?, NULL, 0, 0, 0, NULL)
                """,
                (value, service_date.isoformat(), source_version, now.isoformat()),
            )
        return value

    def get_batch(self, batch_id: str) -> RailTimetableBatch | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT batch_id, service_date, status, source_version, started_at,
                       completed_at, service_count, stop_count, error_count, last_error
                  FROM rail_timetable_batch WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
        return _batch_from_row(row) if row else None

    def latest_staging_batch(self, service_date: date) -> RailTimetableBatch | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT batch_id, service_date, status, source_version, started_at,
                       completed_at, service_count, stop_count, error_count, last_error
                  FROM rail_timetable_batch
                 WHERE service_date = ? AND status = 'STAGING'
                 ORDER BY started_at DESC LIMIT 1
                """,
                (service_date.isoformat(),),
            ).fetchone()
        return _batch_from_row(row) if row else None

    def upsert_service(self, batch_id: str, service: RailServiceInput) -> str:
        batch = self.get_batch(batch_id)
        if batch is None or batch.status != "STAGING":
            raise RailTimetableStoreError("rail service can only be written to a STAGING batch")
        if service.service_date != batch.service_date:
            raise RailTimetableStoreError("rail service date does not match batch date")
        _validate_service(service)
        service_id = _service_id(batch_id, service.train_no_internal)
        with _connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO rail_service(
                  service_id, batch_id, service_date, train_no_internal, train_number,
                  origin_station_code, destination_station_code, summary_fingerprint, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id, train_no_internal) DO UPDATE SET
                  train_number = excluded.train_number,
                  origin_station_code = excluded.origin_station_code,
                  destination_station_code = excluded.destination_station_code,
                  summary_fingerprint = excluded.summary_fingerprint,
                  fetched_at = excluded.fetched_at
                """,
                (
                    service_id,
                    batch_id,
                    service.service_date.isoformat(),
                    service.train_no_internal,
                    service.train_number,
                    service.origin_station_code,
                    service.destination_station_code,
                    service.summary_fingerprint,
                    _aware(service.fetched_at).isoformat(),
                ),
            )
            conn.execute("DELETE FROM rail_stop_time WHERE service_id = ?", (service_id,))
            conn.executemany(
                """
                INSERT INTO rail_stop_time(
                  service_id, stop_sequence, station_code, arrival_time,
                  arrival_day_offset, departure_time, departure_day_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        service_id,
                        stop.stop_sequence,
                        stop.station_code,
                        stop.arrival_time,
                        stop.arrival_day_offset,
                        stop.departure_time,
                        stop.departure_day_offset,
                    )
                    for stop in service.stops
                ],
            )
            self._refresh_batch_counts(conn, batch_id)
        return service_id

    def copy_service(self, source_batch_id: str, target_batch_id: str, train_no_internal: str) -> bool:
        with _connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT service_date, train_no_internal, train_number, origin_station_code,
                       destination_station_code, summary_fingerprint, fetched_at
                  FROM rail_service
                 WHERE batch_id = ? AND train_no_internal = ?
                """,
                (source_batch_id, train_no_internal),
            ).fetchone()
            if row is None:
                return False
            stop_rows = conn.execute(
                """
                SELECT stop_sequence, station_code, arrival_time, arrival_day_offset,
                       departure_time, departure_day_offset
                  FROM rail_stop_time
                 WHERE service_id = ? ORDER BY stop_sequence
                """,
                (_service_id(source_batch_id, train_no_internal),),
            ).fetchall()
        target_batch = self.get_batch(target_batch_id)
        if target_batch is None:
            return False
        service = RailServiceInput(
            service_date=target_batch.service_date,
            train_no_internal=str(row[1]),
            train_number=str(row[2]),
            origin_station_code=str(row[3]),
            destination_station_code=str(row[4]),
            summary_fingerprint=str(row[5]),
            fetched_at=_parse_datetime(str(row[6])),
            stops=tuple(
                RailStopTimeInput(
                    stop_sequence=int(stop[0]),
                    station_code=str(stop[1]),
                    arrival_time=stop[2],
                    arrival_day_offset=int(stop[3]),
                    departure_time=stop[4],
                    departure_day_offset=int(stop[5]),
                )
                for stop in stop_rows
            ),
        )
        self.upsert_service(target_batch_id, service)
        return True

    def copy_services(
        self,
        source_batch_id: str,
        target_batch_id: str,
        train_nos_internal: Sequence[str],
    ) -> set[str]:
        requested = tuple(dict.fromkeys(value.strip() for value in train_nos_internal if value.strip()))
        if not requested:
            return set()
        copied: set[str] = set()
        with _connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute(
                "SELECT service_date FROM rail_timetable_batch WHERE batch_id = ?",
                (source_batch_id,),
            ).fetchone()
            target = conn.execute(
                "SELECT service_date, status FROM rail_timetable_batch WHERE batch_id = ?",
                (target_batch_id,),
            ).fetchone()
            if source is None or target is None:
                raise RailTimetableStoreError("source and target batches are required for service copy")
            if target[1] != "STAGING":
                raise RailTimetableStoreError("copied rail services require a STAGING target batch")
            if source[0] != target[0]:
                raise RailTimetableStoreError("source and target batch dates must match")
            for offset in range(0, len(requested), 500):
                chunk = requested[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT service_id, service_date, train_no_internal, train_number,
                           origin_station_code, destination_station_code,
                           summary_fingerprint, fetched_at
                      FROM rail_service
                     WHERE batch_id = ? AND train_no_internal IN ({placeholders})
                    """,
                    (source_batch_id, *chunk),
                ).fetchall()
                for row in rows:
                    target_service_id = _service_id(target_batch_id, str(row[2]))
                    conn.execute(
                        """
                        INSERT INTO rail_service(
                          service_id, batch_id, service_date, train_no_internal, train_number,
                          origin_station_code, destination_station_code, summary_fingerprint, fetched_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(batch_id, train_no_internal) DO UPDATE SET
                          train_number = excluded.train_number,
                          origin_station_code = excluded.origin_station_code,
                          destination_station_code = excluded.destination_station_code,
                          summary_fingerprint = excluded.summary_fingerprint,
                          fetched_at = excluded.fetched_at
                        """,
                        (target_service_id, target_batch_id, *row[1:]),
                    )
                    conn.execute("DELETE FROM rail_stop_time WHERE service_id = ?", (target_service_id,))
                    conn.execute(
                        """
                        INSERT INTO rail_stop_time(
                          service_id, stop_sequence, station_code, arrival_time,
                          arrival_day_offset, departure_time, departure_day_offset
                        )
                        SELECT ?, stop_sequence, station_code, arrival_time,
                               arrival_day_offset, departure_time, departure_day_offset
                          FROM rail_stop_time WHERE service_id = ?
                        """,
                        (target_service_id, row[0]),
                    )
                    copied.add(str(row[2]))
            self._refresh_batch_counts(conn, target_batch_id)
        return copied

    def active_service_fingerprints(self, service_date: date) -> tuple[str | None, dict[str, str]]:
        with _connect(self.path) as conn:
            batch = conn.execute(
                """
                SELECT batch_id FROM rail_timetable_batch
                 WHERE service_date = ? AND status = 'ACTIVE' LIMIT 1
                """,
                (service_date.isoformat(),),
            ).fetchone()
            if batch is None:
                return None, {}
            rows = conn.execute(
                "SELECT train_no_internal, summary_fingerprint FROM rail_service WHERE batch_id = ?",
                (batch[0],),
            ).fetchall()
        return str(batch[0]), {str(row[0]): str(row[1]) for row in rows}

    def record_error(self, batch_id: str, message: str) -> None:
        safe_message = message.strip()[:500]
        with _connect(self.path) as conn:
            conn.execute(
                """
                UPDATE rail_timetable_batch
                   SET error_count = error_count + 1, last_error = ?
                 WHERE batch_id = ? AND status = 'STAGING'
                """,
                (safe_message, batch_id),
            )

    def activate_batch(self, batch_id: str) -> RailTimetableBatch:
        with _connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT service_date, status, error_count FROM rail_timetable_batch WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if row is None or row[1] != "STAGING":
                raise RailTimetableStoreError("only a STAGING batch can be activated")
            service_count, stop_count = self._batch_counts(conn, batch_id)
            invalid_services = conn.execute(
                """
                SELECT COUNT(*) FROM rail_service service
                 WHERE service.batch_id = ?
                   AND (
                     (SELECT COUNT(*) FROM rail_stop_time stop WHERE stop.service_id = service.service_id) < 2
                     OR NOT EXISTS (
                       SELECT 1 FROM rail_stop_time stop
                        WHERE stop.service_id = service.service_id AND stop.departure_time IS NOT NULL
                     )
                     OR NOT EXISTS (
                       SELECT 1 FROM rail_stop_time stop
                        WHERE stop.service_id = service.service_id AND stop.arrival_time IS NOT NULL
                     )
                   )
                """,
                (batch_id,),
            ).fetchone()[0]
            if service_count <= 0 or stop_count < service_count * 2 or invalid_services:
                raise RailTimetableStoreError(
                    f"batch completeness gate failed: services={service_count}, stops={stop_count}, invalid={invalid_services}"
                )
            now = _utc_now().isoformat()
            conn.execute(
                "UPDATE rail_timetable_batch SET status = 'RETIRED' WHERE service_date = ? AND status = 'ACTIVE'",
                (row[0],),
            )
            conn.execute(
                """
                UPDATE rail_timetable_batch
                   SET status = 'ACTIVE', completed_at = ?, service_count = ?, stop_count = ?
                 WHERE batch_id = ?
                """,
                (now, service_count, stop_count, batch_id),
            )
        activated = self.get_batch(batch_id)
        if activated is None:
            raise RailTimetableStoreError("activated batch disappeared")
        return activated

    def fail_batch(self, batch_id: str, message: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                """
                UPDATE rail_timetable_batch
                   SET status = 'FAILED', completed_at = ?, error_count = error_count + 1, last_error = ?
                 WHERE batch_id = ? AND status = 'STAGING'
                """,
                (_utc_now().isoformat(), message.strip()[:500], batch_id),
            )

    def active_batch(self, service_date: date, *, freshness_hours: int | None) -> RailTimetableBatch | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT batch_id, service_date, status, source_version, started_at,
                       completed_at, service_count, stop_count, error_count, last_error
                  FROM rail_timetable_batch
                 WHERE service_date = ? AND status = 'ACTIVE' LIMIT 1
                """,
                (service_date.isoformat(),),
            ).fetchone()
        batch = _batch_from_row(row) if row else None
        if batch is None or batch.completed_at is None:
            return None
        if freshness_hours is not None and batch.completed_at < _utc_now() - timedelta(hours=freshness_hours):
            return None
        return batch

    def coverage(self, *, freshness_hours: int) -> list[RailTimetableCoverage]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT service_date, status, completed_at, service_count, stop_count
                  FROM rail_timetable_batch
                 WHERE status IN ('ACTIVE', 'FAILED')
                 ORDER BY service_date, status
                """
            ).fetchall()
        cutoff = _utc_now() - timedelta(hours=freshness_hours)
        return [
            RailTimetableCoverage(
                service_date=date.fromisoformat(str(row[0])),
                status=str(row[1]),  # type: ignore[arg-type]
                completed_at=_parse_datetime(row[2]) if row[2] else None,
                service_count=int(row[3]),
                stop_count=int(row[4]),
                fresh=bool(row[1] == "ACTIVE" and row[2] and _parse_datetime(row[2]) >= cutoff),
            )
            for row in rows
        ]

    def cleanup(self, *, window_start: date, retention_days: int) -> int:
        cutoff = window_start - timedelta(days=retention_days)
        with _connect(self.path) as conn:
            expired_rows = conn.execute(
                """
                SELECT batch_id FROM rail_timetable_batch
                 WHERE service_date < ? AND status IN ('RETIRED', 'FAILED')
                """,
                (cutoff.isoformat(),),
            ).fetchall()
            recent_rows = conn.execute(
                """
                SELECT batch_id, service_date, status
                  FROM rail_timetable_batch
                 WHERE service_date >= ? AND status IN ('RETIRED', 'FAILED')
                 ORDER BY service_date, status, COALESCE(completed_at, started_at) DESC, started_at DESC
                """,
                (cutoff.isoformat(),),
            ).fetchall()
            seen: set[tuple[str, str]] = set()
            superseded_rows: list[tuple[str]] = []
            for batch_id, service_date_value, status in recent_rows:
                key = (str(service_date_value), str(status))
                if key in seen:
                    superseded_rows.append((str(batch_id),))
                else:
                    seen.add(key)
            rows_to_delete = [(str(row[0]),) for row in expired_rows]
            rows_to_delete.extend(superseded_rows)
            conn.executemany("DELETE FROM rail_timetable_batch WHERE batch_id = ?", rows_to_delete)
        return len(rows_to_delete)

    def connect_readonly(self) -> sqlite3.Connection:
        return _connect(self.path)

    @staticmethod
    def _batch_counts(conn: sqlite3.Connection, batch_id: str) -> tuple[int, int]:
        service_count = int(
            conn.execute("SELECT COUNT(*) FROM rail_service WHERE batch_id = ?", (batch_id,)).fetchone()[0]
        )
        stop_count = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM rail_stop_time stop
                 JOIN rail_service service ON service.service_id = stop.service_id
                WHERE service.batch_id = ?
                """,
                (batch_id,),
            ).fetchone()[0]
        )
        return service_count, stop_count

    @classmethod
    def _refresh_batch_counts(cls, conn: sqlite3.Connection, batch_id: str) -> None:
        service_count, stop_count = cls._batch_counts(conn, batch_id)
        conn.execute(
            "UPDATE rail_timetable_batch SET service_count = ?, stop_count = ? WHERE batch_id = ?",
            (service_count, stop_count, batch_id),
        )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _validate_service(service: RailServiceInput) -> None:
    if not service.train_no_internal.strip() or not service.train_number.strip():
        raise RailTimetableStoreError("train identity is required")
    if service.train_number[0].upper() not in {"G", "D", "C"}:
        raise RailTimetableStoreError("only G/D/C services are accepted")
    if len(service.stops) < 2:
        raise RailTimetableStoreError("a service requires at least two stops")
    sequences = [stop.stop_sequence for stop in service.stops]
    if sequences != list(range(1, len(sequences) + 1)):
        raise RailTimetableStoreError("stop_sequence must be contiguous and start at 1")
    last_event_minutes: int | None = None
    for stop in service.stops:
        if not stop.station_code.strip():
            raise RailTimetableStoreError("station_code is required")
        if stop.arrival_time is None and stop.departure_time is None:
            raise RailTimetableStoreError("every stop needs arrival or departure time")
        _validate_clock_time(stop.arrival_time)
        _validate_clock_time(stop.departure_time)
        if stop.arrival_day_offset < 0 or stop.departure_day_offset < 0:
            raise RailTimetableStoreError("day offsets cannot be negative")
        arrival_minutes = _absolute_minutes(stop.arrival_time, stop.arrival_day_offset)
        departure_minutes = _absolute_minutes(stop.departure_time, stop.departure_day_offset)
        if arrival_minutes is not None and last_event_minutes is not None and arrival_minutes < last_event_minutes:
            raise RailTimetableStoreError("stop times must be monotonic across the service")
        if arrival_minutes is not None:
            last_event_minutes = arrival_minutes
        if departure_minutes is not None and last_event_minutes is not None and departure_minutes < last_event_minutes:
            raise RailTimetableStoreError("departure cannot precede the previous service event")
        if departure_minutes is not None:
            last_event_minutes = departure_minutes


def _validate_clock_time(value: str | None) -> None:
    if value is None:
        return
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise RailTimetableStoreError(f"invalid clock time: {value}") from exc


def _absolute_minutes(value: str | None, day_offset: int) -> int | None:
    if value is None:
        return None
    parsed = datetime.strptime(value, "%H:%M")
    return day_offset * 24 * 60 + parsed.hour * 60 + parsed.minute


def _batch_from_row(row: Sequence[object]) -> RailTimetableBatch:
    return RailTimetableBatch(
        batch_id=str(row[0]),
        service_date=date.fromisoformat(str(row[1])),
        status=str(row[2]),  # type: ignore[arg-type]
        source_version=str(row[3]),
        started_at=_parse_datetime(str(row[4])),
        completed_at=_parse_datetime(str(row[5])) if row[5] else None,
        service_count=int(row[6]),
        stop_count=int(row[7]),
        error_count=int(row[8]),
        last_error=str(row[9]) if row[9] is not None else None,
    )


def _service_id(batch_id: str, train_no_internal: str) -> str:
    digest = hashlib.sha256(f"{batch_id}\x1f{train_no_internal}".encode("utf-8")).hexdigest()[:24]
    return f"rail_service_{digest}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return _aware(parsed).astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)
