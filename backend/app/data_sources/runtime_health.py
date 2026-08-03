from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

RuntimeFailureKind = Literal[
    "FATAL_PROCESS_EXIT",
    "NON_ZERO_EXIT",
    "STDERR",
    "TIMEOUT",
    "RATE_LIMITED",
    "BUSINESS_ERROR",
    "INVALID_JSON",
    "INVALID_RESPONSE",
    "EXPERIENCE_MODE",
    "EXECUTION_FAILED",
]
CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]


class RuntimeCircuitOpenError(RuntimeError):
    def __init__(self, source_id: str, failure_kind: RuntimeFailureKind | None) -> None:
        super().__init__("provider runtime circuit is open")
        self.source_id = source_id
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    source_id: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    latest_failure_kind: RuntimeFailureKind | None
    latest_error_code: str | None
    latest_failure_retryable: bool | None
    consecutive_failures: int
    circuit_state: CircuitState
    last_event_succeeded: bool | None
    average_latency_ms: int | None


@dataclass
class _RuntimeState:
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    latest_failure_kind: RuntimeFailureKind | None = None
    latest_error_code: str | None = None
    latest_failure_retryable: bool | None = None
    consecutive_failures: int = 0
    category_streak: int = 0
    circuit_state: CircuitState = "CLOSED"
    circuit_open_until: float | None = None
    half_open_probe_in_flight: bool = False
    last_event_succeeded: bool | None = None
    latencies_ms: deque[int] = field(default_factory=deque)


class RuntimeHealthRegistry:
    _THRESHOLDS: dict[RuntimeFailureKind, int] = {
        "FATAL_PROCESS_EXIT": 1,
        "EXECUTION_FAILED": 2,
        "RATE_LIMITED": 2,
        "TIMEOUT": 3,
        "NON_ZERO_EXIT": 3,
        "STDERR": 3,
        "BUSINESS_ERROR": 3,
        "INVALID_JSON": 3,
        "INVALID_RESPONSE": 3,
        "EXPERIENCE_MODE": 3,
    }
    _COOLDOWNS_SECONDS: dict[RuntimeFailureKind, float] = {
        "FATAL_PROCESS_EXIT": 30.0,
        "EXECUTION_FAILED": 15.0,
        "RATE_LIMITED": 15.0,
        "TIMEOUT": 10.0,
        "NON_ZERO_EXIT": 10.0,
        "STDERR": 10.0,
        "BUSINESS_ERROR": 10.0,
        "INVALID_JSON": 10.0,
        "INVALID_RESPONSE": 10.0,
        "EXPERIENCE_MODE": 10.0,
    }

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        latency_window_size: int = 100,
    ) -> None:
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._latency_window_size = max(1, latency_window_size)
        self._lock = threading.Lock()
        self._states: dict[str, _RuntimeState] = {}

    def before_call(self, source_id: str) -> None:
        with self._lock:
            state = self._states.setdefault(source_id, _RuntimeState())
            if state.circuit_state == "CLOSED":
                return
            if state.circuit_state == "HALF_OPEN":
                raise RuntimeCircuitOpenError(source_id, state.latest_failure_kind)
            if state.circuit_open_until is not None and self._monotonic() < state.circuit_open_until:
                raise RuntimeCircuitOpenError(source_id, state.latest_failure_kind)
            state.circuit_state = "HALF_OPEN"
            state.half_open_probe_in_flight = True

    def record_success(self, source_id: str, latency_ms: int) -> None:
        with self._lock:
            state = self._states.setdefault(source_id, _RuntimeState())
            state.last_success_at = self._wall_clock()
            state.last_event_succeeded = True
            state.consecutive_failures = 0
            state.category_streak = 0
            state.circuit_state = "CLOSED"
            state.circuit_open_until = None
            state.half_open_probe_in_flight = False
            state.latencies_ms.append(max(0, latency_ms))
            while len(state.latencies_ms) > self._latency_window_size:
                state.latencies_ms.popleft()

    def record_failure(
        self,
        source_id: str,
        *,
        failure_kind: RuntimeFailureKind,
        error_code: str,
        retryable: bool,
        latency_ms: int | None,
    ) -> None:
        with self._lock:
            state = self._states.setdefault(source_id, _RuntimeState())
            previous_kind = state.latest_failure_kind
            was_half_open = state.circuit_state == "HALF_OPEN"
            state.last_failure_at = self._wall_clock()
            state.last_event_succeeded = False
            state.latest_failure_kind = failure_kind
            state.latest_error_code = error_code
            state.latest_failure_retryable = retryable
            state.consecutive_failures += 1
            state.category_streak = state.category_streak + 1 if previous_kind == failure_kind else 1
            if latency_ms is not None:
                state.latencies_ms.append(max(0, latency_ms))
                while len(state.latencies_ms) > self._latency_window_size:
                    state.latencies_ms.popleft()

            threshold = self._THRESHOLDS[failure_kind]
            if was_half_open or state.category_streak >= threshold:
                state.circuit_state = "OPEN"
                state.circuit_open_until = self._monotonic() + self._COOLDOWNS_SECONDS[failure_kind]
            state.half_open_probe_in_flight = False

    def snapshot(self, source_id: str) -> RuntimeHealthSnapshot | None:
        with self._lock:
            state = self._states.get(source_id)
            if state is None:
                return None
            average_latency_ms = None
            if state.latencies_ms:
                average_latency_ms = round(sum(state.latencies_ms) / len(state.latencies_ms))
            return RuntimeHealthSnapshot(
                source_id=source_id,
                last_success_at=state.last_success_at,
                last_failure_at=state.last_failure_at,
                latest_failure_kind=state.latest_failure_kind,
                latest_error_code=state.latest_error_code,
                latest_failure_retryable=state.latest_failure_retryable,
                consecutive_failures=state.consecutive_failures,
                circuit_state=state.circuit_state,
                last_event_succeeded=state.last_event_succeeded,
                average_latency_ms=average_latency_ms,
            )

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


runtime_health_registry = RuntimeHealthRegistry()
