from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from app.services.rail_timetable_store import RailTimetableStore
from app.services.observability import record_rail_local_search_metrics


logger = logging.getLogger("app.rail_route_search")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TRANSPORT_NODE_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "transport_nodes.json"


@dataclass(frozen=True)
class RailScheduleLeg:
    service_id: str
    service_date: date
    train_no_internal: str
    train_number: str
    origin_station_code: str
    origin_station_name: str
    destination_station_code: str
    destination_station_name: str
    origin_stop_sequence: int
    destination_stop_sequence: int
    departure_at: datetime
    arrival_at: datetime


@dataclass(frozen=True)
class RailScheduleCandidate:
    candidate_id: str
    legs: tuple[RailScheduleLeg, ...]
    departure_at: datetime
    arrival_at: datetime
    total_duration_minutes: int
    transfer_station_code: str | None
    transfer_station_name: str | None
    transfer_wait_minutes: int
    origin_relevance_rank: int
    destination_relevance_rank: int


@dataclass(frozen=True)
class RailRouteSearchDiagnostics:
    elapsed_ms: float
    scanned_leg_count: int
    direct_candidate_count: int
    transfer_candidate_count: int
    returned_candidate_count: int
    pruned_invalid_time: int
    pruned_transfer_window: int
    pruned_total_duration: int
    active_dates: tuple[date, ...]


@dataclass(frozen=True)
class RailRouteSearchResult:
    candidates: tuple[RailScheduleCandidate, ...]
    diagnostics: RailRouteSearchDiagnostics
    snapshot_available: bool


class RailRouteSearch:
    def __init__(self, store: RailTimetableStore | None = None) -> None:
        self.store = store or RailTimetableStore()
        self.station_names = _station_names_by_code()

    def search(
        self,
        *,
        service_date: date,
        origin_station_codes: Iterable[str],
        destination_station_codes: Iterable[str],
        freshness_hours: int,
        max_candidates: int = 24,
        min_transfer_minutes: int = 45,
        max_transfer_wait_minutes: int = 360,
        max_total_duration_minutes: int = 1440,
        origin_relevance: dict[str, int] | None = None,
        destination_relevance: dict[str, int] | None = None,
        preferred_departure_at: datetime | None = None,
    ) -> RailRouteSearchResult:
        started = time.perf_counter()
        origins = tuple(dict.fromkeys(code.strip().upper() for code in origin_station_codes if code.strip()))
        destinations = tuple(dict.fromkeys(code.strip().upper() for code in destination_station_codes if code.strip()))
        if not origins or not destinations:
            return self._empty_result(started, snapshot_available=False)
        active_dates = tuple(
            day
            for day in (service_date, service_date + timedelta(days=1))
            if self.store.active_batch(day, freshness_hours=freshness_hours) is not None
        )
        if service_date not in active_dates:
            return self._empty_result(started, snapshot_available=False)
        origin_rank = origin_relevance or {code: index for index, code in enumerate(origins)}
        destination_rank = destination_relevance or {code: index for index, code in enumerate(destinations)}
        with self.store.connect_readonly() as conn:
            departure_dates = (service_date,)
            direct_rows = self._query_direct_rows(conn, departure_dates, origins, destinations, max_candidates * 8)
            outbound_rows = self._query_outbound_rows(conn, departure_dates, origins, max_candidates * 100)
            inbound_rows = self._query_inbound_rows(conn, active_dates, destinations, max_candidates * 100)
        direct_candidates: list[RailScheduleCandidate] = []
        transfer_candidates: list[RailScheduleCandidate] = []
        pruned_invalid_time = 0
        pruned_transfer_window = 0
        pruned_total_duration = 0
        for row in direct_rows:
            leg = self._leg_from_row(row)
            if leg is None:
                pruned_invalid_time += 1
                continue
            total_minutes = _duration_minutes(leg.departure_at, leg.arrival_at)
            if total_minutes > max_total_duration_minutes:
                pruned_total_duration += 1
                continue
            direct_candidates.append(
                _candidate(
                    (leg,),
                    origin_rank.get(leg.origin_station_code, len(origins)),
                    destination_rank.get(leg.destination_station_code, len(destinations)),
                )
            )
        inbound_by_station: dict[str, list[RailScheduleLeg]] = {}
        for row in inbound_rows:
            leg = self._leg_from_row(row)
            if leg is None:
                pruned_invalid_time += 1
                continue
            inbound_by_station.setdefault(leg.origin_station_code, []).append(leg)
        seen_transfers: set[tuple[str, str]] = set()
        for row in outbound_rows:
            first = self._leg_from_row(row)
            if first is None:
                pruned_invalid_time += 1
                continue
            for second in inbound_by_station.get(first.destination_station_code, ()):
                if first.service_id == second.service_id:
                    continue
                wait = _duration_minutes(first.arrival_at, second.departure_at)
                if wait < min_transfer_minutes or wait > max_transfer_wait_minutes:
                    pruned_transfer_window += 1
                    continue
                total = _duration_minutes(first.departure_at, second.arrival_at)
                if total <= 0:
                    pruned_invalid_time += 1
                    continue
                if total > max_total_duration_minutes:
                    pruned_total_duration += 1
                    continue
                key = (first.service_id, second.service_id)
                if key in seen_transfers:
                    continue
                seen_transfers.add(key)
                transfer_candidates.append(
                    _candidate(
                        (first, second),
                        origin_rank.get(first.origin_station_code, len(origins)),
                        destination_rank.get(second.destination_station_code, len(destinations)),
                    )
                )
        all_candidates = [*direct_candidates, *transfer_candidates]
        all_candidates.sort(
            key=lambda item: (
                len(item.legs),
                item.total_duration_minutes,
                item.transfer_wait_minutes,
                _preferred_departure_delta(item.departure_at, preferred_departure_at),
                item.origin_relevance_rank + item.destination_relevance_rank,
                tuple(leg.train_number for leg in item.legs),
            )
        )
        selected = tuple(all_candidates[:max_candidates])
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        diagnostics = RailRouteSearchDiagnostics(
            elapsed_ms=elapsed_ms,
            scanned_leg_count=len(direct_rows) + len(outbound_rows) + len(inbound_rows),
            direct_candidate_count=len(direct_candidates),
            transfer_candidate_count=len(transfer_candidates),
            returned_candidate_count=len(selected),
            pruned_invalid_time=pruned_invalid_time,
            pruned_transfer_window=pruned_transfer_window,
            pruned_total_duration=pruned_total_duration,
            active_dates=active_dates,
        )
        record_rail_local_search_metrics(
            elapsed_ms=elapsed_ms,
            candidate_count=len(selected),
            scanned_leg_count=diagnostics.scanned_leg_count,
        )
        logger.info(
            "rail_local_route_search service_date=%s elapsed_ms=%s scanned_leg_count=%s direct_candidate_count=%s transfer_candidate_count=%s returned_candidate_count=%s pruned_invalid_time=%s pruned_transfer_window=%s pruned_total_duration=%s",
            service_date.isoformat(),
            elapsed_ms,
            diagnostics.scanned_leg_count,
            diagnostics.direct_candidate_count,
            diagnostics.transfer_candidate_count,
            diagnostics.returned_candidate_count,
            diagnostics.pruned_invalid_time,
            diagnostics.pruned_transfer_window,
            diagnostics.pruned_total_duration,
        )
        return RailRouteSearchResult(selected, diagnostics, snapshot_available=True)

    def _empty_result(self, started: float, *, snapshot_available: bool) -> RailRouteSearchResult:
        diagnostics = RailRouteSearchDiagnostics(
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            scanned_leg_count=0,
            direct_candidate_count=0,
            transfer_candidate_count=0,
            returned_candidate_count=0,
            pruned_invalid_time=0,
            pruned_transfer_window=0,
            pruned_total_duration=0,
            active_dates=(),
        )
        return RailRouteSearchResult((), diagnostics, snapshot_available=snapshot_available)

    @staticmethod
    def _query_direct_rows(conn, active_dates: tuple[date, ...], origins: tuple[str, ...], destinations: tuple[str, ...], limit: int):
        return _query_leg_rows(conn, active_dates, origins=origins, destinations=destinations, limit=limit)

    @staticmethod
    def _query_outbound_rows(conn, active_dates: tuple[date, ...], origins: tuple[str, ...], limit: int):
        return _query_leg_rows(conn, active_dates, origins=origins, destinations=None, limit=limit)

    @staticmethod
    def _query_inbound_rows(conn, active_dates: tuple[date, ...], destinations: tuple[str, ...], limit: int):
        return _query_leg_rows(conn, active_dates, origins=None, destinations=destinations, limit=limit)

    def _leg_from_row(self, row) -> RailScheduleLeg | None:
        service_day = date.fromisoformat(str(row[1]))
        departure_at = _absolute_datetime(service_day, row[10], int(row[11]))
        arrival_at = _absolute_datetime(service_day, row[13], int(row[14]))
        if departure_at is None or arrival_at is None or arrival_at <= departure_at:
            return None
        return RailScheduleLeg(
            service_id=str(row[0]),
            service_date=service_day,
            train_no_internal=str(row[2]),
            train_number=str(row[3]),
            origin_station_code=str(row[4]),
            origin_station_name=self.station_names.get(str(row[4]), str(row[4])),
            destination_station_code=str(row[5]),
            destination_station_name=self.station_names.get(str(row[5]), str(row[5])),
            origin_stop_sequence=int(row[6]),
            destination_stop_sequence=int(row[7]),
            departure_at=departure_at,
            arrival_at=arrival_at,
        )


def _query_leg_rows(
    conn,
    active_dates: tuple[date, ...],
    *,
    origins: tuple[str, ...] | None,
    destinations: tuple[str, ...] | None,
    limit: int,
):
    date_placeholders = ",".join("?" for _ in active_dates)
    clauses = [
        f"service.service_date IN ({date_placeholders})",
        "batch.status = 'ACTIVE'",
        "origin.stop_sequence < destination.stop_sequence",
        "origin.departure_time IS NOT NULL",
        "destination.arrival_time IS NOT NULL",
    ]
    params: list[object] = [item.isoformat() for item in active_dates]
    if origins:
        clauses.append(f"origin.station_code IN ({','.join('?' for _ in origins)})")
        params.extend(origins)
    if destinations:
        clauses.append(f"destination.station_code IN ({','.join('?' for _ in destinations)})")
        params.extend(destinations)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT service.service_id, service.service_date, service.train_no_internal,
               service.train_number, origin.station_code, destination.station_code,
               origin.stop_sequence, destination.stop_sequence,
               origin.arrival_time, origin.arrival_day_offset,
               origin.departure_time, origin.departure_day_offset,
               destination.departure_time, destination.arrival_time, destination.arrival_day_offset
          FROM rail_service service
          JOIN rail_timetable_batch batch ON batch.batch_id = service.batch_id
          JOIN rail_stop_time origin ON origin.service_id = service.service_id
          JOIN rail_stop_time destination ON destination.service_id = service.service_id
         WHERE {' AND '.join(clauses)}
         ORDER BY service.service_date, origin.departure_day_offset, origin.departure_time,
                  destination.arrival_day_offset, destination.arrival_time
         LIMIT ?
        """,
        params,
    ).fetchall()


def _candidate(legs: tuple[RailScheduleLeg, ...], origin_rank: int, destination_rank: int) -> RailScheduleCandidate:
    departure = legs[0].departure_at
    arrival = legs[-1].arrival_at
    transfer_wait = _duration_minutes(legs[0].arrival_at, legs[1].departure_at) if len(legs) == 2 else 0
    identity = "_".join(f"{leg.train_number}_{leg.origin_station_code}_{leg.destination_station_code}" for leg in legs)
    return RailScheduleCandidate(
        candidate_id=f"schedule_{departure.date().isoformat()}_{identity}",
        legs=legs,
        departure_at=departure,
        arrival_at=arrival,
        total_duration_minutes=_duration_minutes(departure, arrival),
        transfer_station_code=legs[0].destination_station_code if len(legs) == 2 else None,
        transfer_station_name=legs[0].destination_station_name if len(legs) == 2 else None,
        transfer_wait_minutes=transfer_wait,
        origin_relevance_rank=origin_rank,
        destination_relevance_rank=destination_rank,
    )


def _absolute_datetime(service_date: date, value: str | None, day_offset: int) -> datetime | None:
    if value is None:
        return None
    parsed_time = datetime.strptime(str(value), "%H:%M").time()
    return datetime.combine(service_date + timedelta(days=day_offset), parsed_time, tzinfo=SHANGHAI_TZ)


def _duration_minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _preferred_departure_delta(value: datetime, preferred: datetime | None) -> int:
    if preferred is None:
        return 0
    candidate = value
    reference = preferred if preferred.tzinfo is not None else preferred.replace(tzinfo=SHANGHAI_TZ)
    return abs(int((candidate - reference.astimezone(SHANGHAI_TZ)).total_seconds() // 60))


def _station_names_by_code() -> dict[str, str]:
    payload = json.loads(TRANSPORT_NODE_CATALOG_PATH.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for station in payload.get("stations", ()):
        code = str(station.get("station_code") or "").strip().upper()
        name = str(station.get("node_name") or "").strip()
        if code and name and code not in result:
            result[code] = name
    return result
