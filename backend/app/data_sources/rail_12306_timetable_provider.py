from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, MutableMapping

import httpx

from app.data_sources.rail_providers import station_code_for_name
from app.services.rail_timetable_store import RailServiceInput, RailStopTimeInput


logger = logging.getLogger("app.rail_timetable_import")

DEFAULT_SEARCH_BASE_URL = "https://search.12306.cn"
DEFAULT_TICKET_BASE_URL = "https://kyfw.12306.cn"
DEFAULT_USER_AGENT = "AITravelPlanner/0.1 low-frequency-timetable-import"
SOURCE_VERSION = "12306-search-v1+queryTrainInfo-v1"
MAX_SEARCH_RESULTS = 200


class RailTimetableProviderError(RuntimeError):
    pass


class RailTimetableAccessControlError(RailTimetableProviderError):
    pass


class RailTimetableTemporaryError(RailTimetableProviderError):
    pass


@dataclass(frozen=True)
class DiscoveredRailService:
    service_date: date
    train_no_internal: str
    train_number: str
    origin_station_name: str
    destination_station_name: str
    total_stop_count: int | None
    summary_fingerprint: str


@dataclass(frozen=True)
class DiscoveryDiagnostics:
    query_count: int
    split_prefix_count: int
    service_count: int
    response_hashes: tuple[str, ...]


class Rail12306TimetableProvider:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        search_base_url: str = DEFAULT_SEARCH_BASE_URL,
        ticket_base_url: str = DEFAULT_TICKET_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        interval_seconds: float = 1.5,
        timeout_seconds: float = 15.0,
        max_temporary_retries: int = 2,
    ) -> None:
        if interval_seconds < 1.0:
            raise ValueError("12306 timetable import interval must be at least 1 second")
        self.search_base_url = search_base_url.rstrip("/")
        self.ticket_base_url = ticket_base_url.rstrip("/")
        self.interval_seconds = interval_seconds
        self.max_temporary_retries = max_temporary_retries
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._last_request_at: float | None = None

    def discover_services(
        self,
        service_date: date,
        *,
        prefixes: Iterable[str] = ("G", "D", "C"),
        max_prefix_length: int = 6,
        max_queries: int | None = None,
        resume_state: MutableMapping[str, Any] | None = None,
        checkpoint_callback: Callable[[], None] | None = None,
    ) -> tuple[list[DiscoveredRailService], DiscoveryDiagnostics]:
        requested_prefixes = [prefix.strip().upper() for prefix in prefixes if prefix.strip()]
        if not requested_prefixes or any(prefix[0] not in {"G", "D", "C"} for prefix in requested_prefixes):
            raise ValueError("discovery prefixes must start with G, D or C")
        state = resume_state if resume_state is not None else {}
        state_matches = (
            state.get("version") == 1
            and state.get("service_date") == service_date.isoformat()
            and state.get("requested_prefixes") == requested_prefixes
        )
        if state_matches:
            pending = [str(value) for value in state.get("pending_prefixes", [])]
            services = {
                str(key): _discovery_from_state(value, service_date)
                for key, value in dict(state.get("services", {})).items()
            }
            query_count = int(state.get("query_count", 0))
            split_count = int(state.get("split_prefix_count", 0))
            response_hashes = [str(value) for value in state.get("response_hashes", [])]
        else:
            pending = list(requested_prefixes)
            services: dict[str, DiscoveredRailService] = {}
            query_count = 0
            split_count = 0
            response_hashes: list[str] = []
            state.clear()
            state.update(
                {
                    "version": 1,
                    "service_date": service_date.isoformat(),
                    "requested_prefixes": requested_prefixes,
                    "pending_prefixes": pending,
                    "services": {},
                    "query_count": 0,
                    "split_prefix_count": 0,
                    "response_hashes": [],
                    "status": "RUNNING",
                }
            )
            if checkpoint_callback is not None:
                checkpoint_callback()
        invocation_query_count = 0
        while pending:
            prefix = pending[0]
            if max_queries is not None and invocation_query_count >= max_queries:
                break
            payload, response_hash = self._get_json(
                f"{self.search_base_url}/search/v1/train/search",
                params={"keyword": prefix, "date": service_date.strftime("%Y%m%d")},
                operation="train_search",
            )
            pending.pop(0)
            query_count += 1
            invocation_query_count += 1
            response_hashes.append(response_hash)
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise RailTimetableProviderError("12306 train search data is not a list")
            if len(rows) >= MAX_SEARCH_RESULTS:
                if len(prefix) >= max_prefix_length:
                    raise RailTimetableProviderError(
                        f"12306 train search remains capped at prefix {prefix}; refusing incomplete activation"
                    )
                pending.extend(f"{prefix}{digit}" for digit in "0123456789")
                split_count += 1
            else:
                for row in rows:
                    service = _parse_discovery_row(row, service_date)
                    if service is None or not service.train_number.startswith(prefix):
                        continue
                    services[service.train_no_internal] = service
            state.update(
                {
                    "pending_prefixes": pending,
                    "services": {
                        key: _discovery_to_state(value)
                        for key, value in services.items()
                    },
                    "query_count": query_count,
                    "split_prefix_count": split_count,
                    "response_hashes": response_hashes,
                    "status": "RUNNING" if pending else "COMPLETE",
                }
            )
            if checkpoint_callback is not None:
                checkpoint_callback()
        ordered = sorted(services.values(), key=lambda item: (item.train_number, item.train_no_internal))
        logger.info(
            "rail_timetable_discovery_complete service_date=%s query_count=%s split_prefix_count=%s service_count=%s",
            service_date.isoformat(),
            query_count,
            split_count,
            len(ordered),
        )
        return ordered, DiscoveryDiagnostics(
            query_count=query_count,
            split_prefix_count=split_count,
            service_count=len(ordered),
            response_hashes=tuple(response_hashes),
        )

    def discover_exact_services(
        self,
        service_date: date,
        train_numbers: Iterable[str],
    ) -> tuple[list[DiscoveredRailService], DiscoveryDiagnostics]:
        services: dict[str, DiscoveredRailService] = {}
        response_hashes: list[str] = []
        query_count = 0
        for raw_train_number in train_numbers:
            train_number = raw_train_number.strip().upper()
            if not train_number or train_number[0] not in {"G", "D", "C"}:
                raise ValueError("exact train numbers must start with G, D or C")
            payload, response_hash = self._get_json(
                f"{self.search_base_url}/search/v1/train/search",
                params={"keyword": train_number, "date": service_date.strftime("%Y%m%d")},
                operation="train_search_exact",
            )
            query_count += 1
            response_hashes.append(response_hash)
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise RailTimetableProviderError("12306 train search data is not a list")
            matched = [
                parsed
                for row in rows
                if (parsed := _parse_discovery_row(row, service_date)) is not None
                and parsed.train_number == train_number
            ]
            if len(matched) > 1:
                raise RailTimetableProviderError(f"12306 returned ambiguous identity for {train_number}")
            if matched:
                services[matched[0].train_no_internal] = matched[0]
        ordered = sorted(services.values(), key=lambda item: (item.train_number, item.train_no_internal))
        return ordered, DiscoveryDiagnostics(
            query_count=query_count,
            split_prefix_count=0,
            service_count=len(ordered),
            response_hashes=tuple(response_hashes),
        )

    def fetch_complete_service(self, discovered: DiscoveredRailService) -> RailServiceInput:
        payload, response_hash = self._get_json(
            f"{self.ticket_base_url}/otn/queryTrainInfo/query",
            params={
                "leftTicketDTO.train_no": discovered.train_no_internal,
                "leftTicketDTO.train_date": discovered.service_date.isoformat(),
                "rand_code": "",
            },
            operation="train_detail",
            referer=f"{self.ticket_base_url}/otn/leftTicket/init",
        )
        if payload.get("status") is False or payload.get("httpstatus") not in (None, 200):
            raise RailTimetableProviderError("12306 train detail reported business failure")
        data = payload.get("data")
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) < 2:
            raise RailTimetableProviderError("12306 train detail returned fewer than two stops")
        stops = tuple(
            _parse_stop_row(row, index, is_last=index == len(rows))
            for index, row in enumerate(rows, start=1)
        )
        train_numbers = {
            str(row.get("station_train_code") or "").strip().upper()
            for row in rows
            if isinstance(row, dict)
        }
        train_numbers.discard("")
        if discovered.train_number not in train_numbers:
            raise RailTimetableProviderError("12306 train detail identity does not match discovery result")
        return RailServiceInput(
            service_date=discovered.service_date,
            train_no_internal=discovered.train_no_internal,
            train_number=discovered.train_number,
            origin_station_code=stops[0].station_code,
            destination_station_code=stops[-1].station_code,
            summary_fingerprint=discovered.summary_fingerprint,
            fetched_at=datetime.now(tz=timezone.utc),
            stops=stops,
        )

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        operation: str,
        referer: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        headers = {"Referer": referer} if referer else None
        for attempt in range(self.max_temporary_retries + 1):
            self._wait_for_interval()
            started = time.monotonic()
            try:
                response = self.client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_temporary_retries:
                    raise RailTimetableTemporaryError(f"12306 {operation} transport failure") from exc
                time.sleep(min(8.0, 2.0**attempt))
                continue
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            response_hash = hashlib.sha256(response.content).hexdigest()
            logger.info(
                "rail_timetable_provider_response operation=%s status_code=%s elapsed_ms=%s response_hash=%s bytes=%s",
                operation,
                response.status_code,
                elapsed_ms,
                response_hash,
                len(response.content),
            )
            if response.status_code == 429:
                raise RailTimetableAccessControlError("12306 rate limit encountered; import paused")
            if response.status_code in {401, 403, 418}:
                raise RailTimetableAccessControlError("12306 access control challenge encountered; import paused")
            if response.status_code >= 500:
                if attempt >= self.max_temporary_retries:
                    raise RailTimetableTemporaryError(f"12306 {operation} server failure")
                time.sleep(min(8.0, 2.0**attempt))
                continue
            if response.status_code != 200:
                raise RailTimetableProviderError(f"12306 {operation} returned HTTP {response.status_code}")
            content_type = (response.headers.get("content-type") or "").lower()
            text_prefix = response.text[:300].lower()
            if "json" not in content_type or any(
                marker in text_prefix for marker in ("captcha", "验证码", "访问频繁", "安全验证")
            ):
                raise RailTimetableAccessControlError("12306 returned a challenge or non-JSON response; import paused")
            try:
                payload = response.json()
            except ValueError as exc:
                raise RailTimetableProviderError(f"12306 {operation} response is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise RailTimetableProviderError(f"12306 {operation} response is not a JSON object")
            return payload, response_hash
        raise RailTimetableTemporaryError(f"12306 {operation} exhausted retry budget")

    def _wait_for_interval(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self.interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _parse_discovery_row(value: Any, service_date: date) -> DiscoveredRailService | None:
    if not isinstance(value, dict):
        raise RailTimetableProviderError("12306 train search row is not an object")
    train_number = str(value.get("station_train_code") or "").strip().upper()
    if not train_number or train_number[0] not in {"G", "D", "C"}:
        return None
    train_no_internal = str(value.get("train_no") or "").strip()
    origin = str(value.get("from_station") or "").strip()
    destination = str(value.get("to_station") or "").strip()
    if not train_no_internal or not origin or not destination:
        raise RailTimetableProviderError("12306 train search row is missing identity fields")
    total_text = str(value.get("total_num") or "").strip()
    total_count = int(total_text) if total_text.isdigit() else None
    fingerprint_payload = {
        "service_date": service_date.isoformat(),
        "train_no": train_no_internal,
        "train_number": train_number,
        "origin": origin,
        "destination": destination,
        "total_stop_count": total_count,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DiscoveredRailService(
        service_date=service_date,
        train_no_internal=train_no_internal,
        train_number=train_number,
        origin_station_name=origin,
        destination_station_name=destination,
        total_stop_count=total_count,
        summary_fingerprint=fingerprint,
    )


def _discovery_to_state(value: DiscoveredRailService) -> dict[str, Any]:
    return {
        "train_no_internal": value.train_no_internal,
        "train_number": value.train_number,
        "origin_station_name": value.origin_station_name,
        "destination_station_name": value.destination_station_name,
        "total_stop_count": value.total_stop_count,
        "summary_fingerprint": value.summary_fingerprint,
    }


def _discovery_from_state(value: Any, service_date: date) -> DiscoveredRailService:
    if not isinstance(value, dict):
        raise RailTimetableProviderError("timetable discovery checkpoint is malformed")
    train_no_internal = str(value.get("train_no_internal") or "").strip()
    train_number = str(value.get("train_number") or "").strip().upper()
    origin = str(value.get("origin_station_name") or "").strip()
    destination = str(value.get("destination_station_name") or "").strip()
    fingerprint = str(value.get("summary_fingerprint") or "").strip()
    if not train_no_internal or not train_number or not origin or not destination or not fingerprint:
        raise RailTimetableProviderError("timetable discovery checkpoint is missing identity fields")
    total_stop_count = value.get("total_stop_count")
    if total_stop_count is not None and not isinstance(total_stop_count, int):
        raise RailTimetableProviderError("timetable discovery checkpoint has an invalid stop count")
    return DiscoveredRailService(
        service_date=service_date,
        train_no_internal=train_no_internal,
        train_number=train_number,
        origin_station_name=origin,
        destination_station_name=destination,
        total_stop_count=total_stop_count,
        summary_fingerprint=fingerprint,
    )


def _parse_stop_row(value: Any, fallback_sequence: int, *, is_last: bool) -> RailStopTimeInput:
    if not isinstance(value, dict):
        raise RailTimetableProviderError("12306 train detail stop is not an object")
    station_name = str(value.get("station_name") or "").strip()
    station_code = station_code_for_name(station_name)
    if not station_name or not station_code:
        raise RailTimetableProviderError(f"station code missing for timetable stop: {station_name or '<empty>'}")
    day_text = str(value.get("arrive_day_diff") or "0").strip()
    day_offset = int(day_text) if day_text.isdigit() else 0
    arrival = None if fallback_sequence == 1 else _clock_or_none(value.get("arrive_time"))
    # Some terminal rows contain a stale start_time that can even precede the
    # arrival (C119 returned 14:24 after a 14:25 arrival). A terminal station
    # has no departure in our service model, regardless of that source noise.
    departure = None if is_last else _clock_or_none(value.get("start_time"))
    return RailStopTimeInput(
        # queryTrainInfo may retain the parent service's sparse station_no values
        # after a train-number change (for example 01 -> 07 for a two-stop C1017
        # response). Our snapshot sequence is relative to the returned service, so
        # normalize it to a contiguous 1-based order before the store validates it.
        stop_sequence=fallback_sequence,
        station_code=station_code,
        arrival_time=arrival,
        arrival_day_offset=day_offset,
        departure_time=departure,
        departure_day_offset=day_offset,
    )


def _clock_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"", "----", "--"}:
        return None
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise RailTimetableProviderError(f"invalid 12306 stop time: {text}") from exc
    return text
