from __future__ import annotations

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.data_sources import rail_12306_timetable_provider as provider_module
from app.data_sources.rail_12306_timetable_provider import (
    Rail12306TimetableProvider,
    RailTimetableAccessControlError,
    RailTimetableBudgetExceeded,
    _parse_discovery_row,
)


SERVICE_DATE = date(2026, 10, 14)
SEARCH_ROW = {
    "date": "20261014",
    "from_station": "北京南",
    "station_train_code": "G1",
    "to_station": "上海虹桥",
    "total_num": "3",
    "train_no": "24000000G100",
}


class ImportClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def import_clock(monkeypatch: pytest.MonkeyPatch) -> ImportClock:
    clock = ImportClock()
    monkeypatch.setattr(
        provider_module,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
    )
    return clock


def _detail_response() -> dict:
    return {
        "status": True,
        "httpstatus": 200,
        "data": {
            "data": [
                {
                    "station_train_code": "G1", "station_name": "北京南",
                    "station_no": "01", "arrive_time": "----", "start_time": "06:30",
                    "arrive_day_diff": "0", "running_time": "00:00",
                },
                {
                    "station_train_code": "G1", "station_name": "南京南",
                    "station_no": "02", "arrive_time": "10:00", "start_time": "10:02",
                    "arrive_day_diff": "0", "running_time": "03:30",
                },
                {
                    "station_train_code": "G1", "station_name": "上海虹桥",
                    "station_no": "03", "arrive_time": "12:30", "start_time": "----",
                    "arrive_day_diff": "0", "running_time": "06:00",
                },
            ],
        },
    }


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        ("start_time", "06:30", "06:31"),
        ("arrive_time", "12:30", "12:31"),
        ("start_day_diff", "0", "1"),
        ("arrive_day_diff", "0", "1"),
        ("running_time", "06:00", "06:01"),
        ("departure_time", "06:30", "06:31"),
        ("arrival_time", "12:30", "12:31"),
        ("departure_day_diff", 0, 1),
        ("arrival_day_diff", 0, 1),
    ],
)
def test_summary_fingerprint_detects_available_timetable_changes(field, before, after) -> None:
    previous = _parse_discovery_row({**SEARCH_ROW, field: before}, SERVICE_DATE)
    changed = _parse_discovery_row({**SEARCH_ROW, field: after}, SERVICE_DATE)
    without_timing = _parse_discovery_row(SEARCH_ROW, SERVICE_DATE)
    assert previous is not None and changed is not None and without_timing is not None
    assert previous.summary_fingerprint != changed.summary_fingerprint
    assert previous.summary_fingerprint != without_timing.summary_fingerprint
    assert previous.train_no_internal == changed.train_no_internal


def test_search_rows_without_timing_keep_legacy_fingerprint() -> None:
    service = _parse_discovery_row(SEARCH_ROW, SERVICE_DATE)
    legacy_summary = {
        "service_date": "2026-10-14",
        "train_no": "24000000G100",
        "train_number": "G1",
        "origin": "北京南",
        "destination": "上海虹桥",
        "total_stop_count": 3,
    }
    legacy_fingerprint = hashlib.sha256(
        json.dumps(legacy_summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert service is not None and service.summary_fingerprint == legacy_fingerprint


def test_metrics_separate_actual_http_attempts_network_retries_and_waits(import_clock) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            import_clock.now += 0.2
            return httpx.Response(503, json={"error": "temporary"})
        if attempts == 2:
            import_clock.now += 0.3
            raise httpx.ReadTimeout("temporary", request=request)
        if "train/search" in request.url.path:
            import_clock.now += 0.4
            return httpx.Response(200, json={"data": [SEARCH_ROW]})
        import_clock.now += 0.5
        return httpx.Response(200, json=_detail_response())

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), interval_seconds=1.0,
    )
    discovered, diagnostics = provider.discover_exact_services(SERVICE_DATE, ["G1"])
    details = provider.fetch_complete_service(discovered[0])
    assert len(details.stops) == 3
    assert diagnostics.query_count == 1
    assert provider.request_metrics == pytest.approx({
        "requests": 4, "network_seconds": 1.4,
        "discovery_requests": 3, "detail_requests": 1,
        "discovery_network_seconds": 0.9, "detail_network_seconds": 0.5,
        "temporary_retry_count": 2, "retry_wait_seconds": 3.0, "interval_wait_seconds": 0.6,
    })
    snapshot = provider.metrics_snapshot()
    snapshot["requests"] = 99
    assert provider.request_metrics["requests"] == 4


def test_same_discovery_generation_resumes_pending_prefixes_and_completed_state(import_clock) -> None:
    queried = []

    def handler(request: httpx.Request) -> httpx.Response:
        prefix = request.url.params["keyword"]
        queried.append(prefix)
        row = dict(SEARCH_ROW)
        row["station_train_code"] = "G1" if prefix == "G" else "D1"
        row["train_no"] = f"internal_{prefix}1"
        return httpx.Response(200, json={"data": [row]})

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), interval_seconds=1.0,
    )
    state = {}
    checkpoint_status = []
    first, _ = provider.discover_services(
        SERVICE_DATE, prefixes=("G", "D"), max_queries=1, resume_state=state,
        checkpoint_callback=lambda: checkpoint_status.append(state["status"]),
    )
    assert len(first) == 1 and state["pending_prefixes"] == ["D"]
    complete, diagnostics = provider.discover_services(
        SERVICE_DATE, prefixes=("G", "D"), resume_state=state,
    )
    resumed, _ = provider.discover_services(
        SERVICE_DATE, prefixes=("G", "D"), resume_state=state,
    )
    assert queried == ["G", "D"]
    assert len(complete) == len(resumed) == 2
    assert state["status"] == "COMPLETE" and diagnostics.query_count == 2
    assert checkpoint_status == ["RUNNING", "RUNNING"]
    assert provider.request_metrics["requests"] == 2


@pytest.mark.parametrize("status", [429, 401, 403, 418])
def test_access_control_stops_immediately_without_retry_or_checkpoint_progress(status, import_clock) -> None:
    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json={}))),
    )
    state = {}
    with pytest.raises(RailTimetableAccessControlError):
        provider.discover_services(SERVICE_DATE, prefixes=("G",), resume_state=state)
    assert state["pending_prefixes"] == ["G"]
    assert provider.request_metrics["requests"] == 1
    assert provider.request_metrics["temporary_retry_count"] == 0
    assert provider.request_metrics["retry_wait_seconds"] == 0


def test_challenge_response_is_not_retried(import_clock) -> None:
    provider = Rail12306TimetableProvider(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text="<html>captcha</html>", headers={"content-type": "text/html"}),
    )))
    with pytest.raises(RailTimetableAccessControlError):
        provider.discover_services(SERVICE_DATE, prefixes=("G",))
    assert provider.request_metrics["requests"] == 1


def test_access_challenge_takes_priority_when_request_also_consumes_budget(import_clock) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        import_clock.now += 1.0
        return httpx.Response(200, text="captcha", headers={"content-type": "text/html"})

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        remaining_budget=lambda: 1.0 - import_clock.now,
    )
    with pytest.raises(RailTimetableAccessControlError):
        provider.discover_services(SERVICE_DATE, prefixes=("G",))
    assert provider.request_metrics["requests"] == 1


def test_exhausted_budget_stops_before_http_and_preserves_pending_prefix(import_clock) -> None:
    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))),
        remaining_budget=lambda: 0.0,
    )
    state = {}
    with pytest.raises(RailTimetableBudgetExceeded):
        provider.discover_services(SERVICE_DATE, prefixes=("G",), resume_state=state)
    assert state["pending_prefixes"] == ["G"]
    assert provider.request_metrics["requests"] == 0


def test_request_timeout_uses_remaining_budget_and_expiry_is_not_transport_retry(import_clock) -> None:
    timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        import_clock.now += 2.0
        raise httpx.ReadTimeout("deadline", request=request)

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), timeout_seconds=15.0,
        remaining_budget=lambda: 2.0 - import_clock.now,
    )
    with pytest.raises(RailTimetableBudgetExceeded):
        provider.discover_services(SERVICE_DATE, prefixes=("G",))
    assert timeouts == [2.0]
    assert provider.request_metrics["requests"] == 1
    assert provider.request_metrics["network_seconds"] == pytest.approx(2.0)
    assert provider.request_metrics["temporary_retry_count"] == 0


@pytest.mark.parametrize("transport_error", [False, True])
def test_retry_wait_is_budget_bounded_and_excluded_from_network_time(transport_error, import_clock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import_clock.now += 0.2
        if transport_error:
            raise httpx.ReadTimeout("temporary", request=request)
        return httpx.Response(503, json={})

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        remaining_budget=lambda: 0.5 - import_clock.now,
    )
    state = {}
    with pytest.raises(RailTimetableBudgetExceeded):
        provider.discover_services(SERVICE_DATE, prefixes=("G",), resume_state=state)
    assert import_clock.now == pytest.approx(0.5)
    assert state["pending_prefixes"] == ["G"]
    assert provider.request_metrics["network_seconds"] == pytest.approx(0.2)
    assert provider.request_metrics["retry_wait_seconds"] == pytest.approx(0.3)
    assert provider.request_metrics["requests"] == 1


def test_interval_wait_stops_at_budget_without_next_http(import_clock) -> None:
    queried = []

    def handler(request: httpx.Request) -> httpx.Response:
        queried.append(request.url.params["keyword"])
        import_clock.now += 0.2
        return httpx.Response(200, json={"data": [SEARCH_ROW]})

    provider = Rail12306TimetableProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), interval_seconds=1.0,
        remaining_budget=lambda: 0.5 - import_clock.now,
    )
    state = {}
    with pytest.raises(RailTimetableBudgetExceeded):
        provider.discover_services(SERVICE_DATE, prefixes=("G", "D"), resume_state=state)
    assert queried == ["G"] and state["pending_prefixes"] == ["D"]
    assert provider.request_metrics["interval_wait_seconds"] == pytest.approx(0.3)
    assert provider.request_metrics["requests"] == 1
