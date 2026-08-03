from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.data_sources.runtime_health import (
    RuntimeCircuitOpenError,
    RuntimeFailureKind,
    RuntimeHealthRegistry,
    runtime_health_registry,
)

logger = logging.getLogger("app.flyai")

_LOCATION_RE = re.compile(r"^[A-Za-z0-9\u3400-\u9fff \-\u00b7]{1,80}$")
_OPTION_RE = re.compile(r"^[A-Za-z0-9\u3400-\u9fff ,\-\u00b7]{1,80}$")
_CERTIFIED_CLI_VERSION = "1.0.16"
_CERTIFIED_PATCHED_BUNDLE_SHA256 = "249791ae4274cdec3bbb9babb2788ceada291f94623f7c16d3901d16c8e41f58"


class FlyAIClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        failure_kind: RuntimeFailureKind | None = None,
        exit_code: int | None = None,
        elapsed_ms: int | None = None,
        circuit_open: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.retryable = retryable
        self.failure_kind = failure_kind
        self.exit_code = exit_code
        self.elapsed_ms = elapsed_ms
        self.circuit_open = circuit_open


@dataclass(frozen=True)
class FlyAICommandResult:
    payload: dict[str, Any]
    response_hash: str
    item_count: int
    elapsed_ms: int


Runner = Callable[..., subprocess.CompletedProcess[str]]


class FlyAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        executable: str,
        timeout_seconds: float,
        runner: Runner = subprocess.run,
        base_environment: Mapping[str, str] | None = None,
        runtime_registry: RuntimeHealthRegistry = runtime_health_registry,
    ) -> None:
        if not api_key:
            raise FlyAIClientError("FLIGGY_API_KEY_MISSING", "FlyAI API key is missing", retryable=False)
        if not executable.strip():
            raise FlyAIClientError("FLIGGY_EXECUTABLE_MISSING", "FlyAI executable is missing", retryable=False)
        self._api_key = api_key
        self.executable = _resolved_executable(executable.strip())
        certified_bundle = _certified_bundle_if_present(self.executable)
        self._command_prefix = _runtime_command_prefix(self.executable, certified_bundle)
        self.timeout_seconds = timeout_seconds
        self._runner = runner
        self._base_environment = dict(base_environment or os.environ)
        self._runtime_registry = runtime_registry

    def search_flight(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        non_stop: bool | None,
        cabin: str | None = None,
        max_price: int | None = None,
        sort_type: int = 3,
    ) -> FlyAICommandResult:
        args = self._common_args(origin, destination, departure_date)
        if non_stop is not None:
            args.extend(("--journey-type", "1" if non_stop else "2"))
        if cabin:
            args.extend(("--seat-class-name", _validated_option(cabin, "cabin")))
        if max_price is not None:
            args.extend(("--max-price", str(_validated_positive_int(max_price, "max_price"))))
        args.extend(("--sort-type", str(_validated_sort_type(sort_type))))
        return self._run("search-flight", args)

    def search_train(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        train_number: str | None = None,
        seat: str | None = None,
        sort_type: int = 3,
    ) -> FlyAICommandResult:
        args = self._common_args(origin, destination, departure_date)
        args.extend(("--journey-type", "1"))
        if train_number:
            args.extend(("--transport-no", _validated_option(train_number, "train_number")))
        if seat:
            args.extend(("--seat-class-name", _validated_option(seat, "seat")))
        args.extend(("--sort-type", str(_validated_sort_type(sort_type))))
        return self._run("search-train", args)

    def _common_args(self, origin: str, destination: str, departure_date: date) -> list[str]:
        return [
            "--origin",
            _validated_location(origin, "origin"),
            "--destination",
            _validated_location(destination, "destination"),
            "--dep-date",
            departure_date.isoformat(),
        ]

    def _run(self, command: str, arguments: Sequence[str]) -> FlyAICommandResult:
        argv = [*self._command_prefix, command, *arguments]
        environment = dict(self._base_environment)
        environment["FLYAI_API_KEY"] = self._api_key
        try:
            self._runtime_registry.before_call("fliggy_flyai")
        except RuntimeCircuitOpenError as exc:
            raise FlyAIClientError(
                "FLIGGY_CIRCUIT_OPEN",
                "FlyAI runtime circuit is open",
                retryable=True,
                failure_kind=exc.failure_kind,
                circuit_open=True,
            ) from exc
        started_at = _monotonic_ms()
        try:
            completed = self._runner(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = max(0, _monotonic_ms() - started_at)
            raise self._recorded_error(
                "FLIGGY_TIMEOUT",
                "FlyAI CLI timed out",
                retryable=True,
                failure_kind="TIMEOUT",
                elapsed_ms=elapsed_ms,
            ) from exc
        except (OSError, UnicodeError) as exc:
            elapsed_ms = max(0, _monotonic_ms() - started_at)
            raise self._recorded_error(
                "FLIGGY_EXECUTION_FAILED",
                "FlyAI CLI could not be executed",
                retryable=True,
                failure_kind="EXECUTION_FAILED",
                elapsed_ms=elapsed_ms,
            ) from exc

        elapsed_ms = max(0, _monotonic_ms() - started_at)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        response_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        if completed.returncode != 0:
            failure_kind: RuntimeFailureKind = (
                "FATAL_PROCESS_EXIT" if _is_fatal_process_exit(completed.returncode, stderr) else "NON_ZERO_EXIT"
            )
            error_code = "FLIGGY_FATAL_PROCESS_EXIT" if failure_kind == "FATAL_PROCESS_EXIT" else "FLIGGY_NON_ZERO_EXIT"
            logger.warning(
                "flyai_cli_failed command=%s failure_kind=%s exit_code=%s elapsed_ms=%s response_hash=%s",
                command,
                failure_kind,
                completed.returncode,
                elapsed_ms,
                response_hash,
            )
            raise self._recorded_error(
                error_code,
                "FlyAI CLI terminated unexpectedly" if failure_kind == "FATAL_PROCESS_EXIT" else "FlyAI CLI returned a non-zero exit code",
                retryable=True,
                failure_kind=failure_kind,
                exit_code=completed.returncode,
                elapsed_ms=elapsed_ms,
            )
        if stderr.strip():
            raise self._recorded_error(
                "FLIGGY_STDERR",
                "FlyAI CLI wrote unexpected stderr output",
                retryable=True,
                failure_kind="STDERR",
                elapsed_ms=elapsed_ms,
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise self._recorded_error(
                "FLIGGY_INVALID_JSON",
                "FlyAI CLI stdout is not one complete JSON object",
                retryable=True,
                failure_kind="INVALID_JSON",
                elapsed_ms=elapsed_ms,
            ) from exc
        if not isinstance(payload, dict):
            raise self._recorded_error(
                "FLIGGY_INVALID_RESPONSE",
                "FlyAI CLI response must be a JSON object",
                retryable=True,
                failure_kind="INVALID_RESPONSE",
                elapsed_ms=elapsed_ms,
            )
        status = payload.get("status")
        message = str(payload.get("message") or "")
        system_message = str(payload.get("systemMessage") or "")
        if "体验模式" in system_message or "experience mode" in system_message.lower():
            raise self._recorded_error(
                "FLIGGY_EXPERIENCE_MODE",
                "FlyAI response is limited to experience mode",
                retryable=False,
                failure_kind="EXPERIENCE_MODE",
                elapsed_ms=elapsed_ms,
            )
        if type(status) is not int or status != 0 or message.lower() != "success":
            business_signal = f"{message} {system_message}".lower()
            if any(marker in business_signal for marker in ("rate limit", "too many", "quota", "频率", "次数", "限制")):
                raise self._recorded_error(
                    "FLIGGY_RATE_LIMITED",
                    "FlyAI rate limit was reached",
                    retryable=True,
                    failure_kind="RATE_LIMITED",
                    elapsed_ms=elapsed_ms,
                )
            raise self._recorded_error(
                "FLIGGY_BUSINESS_ERROR",
                "FlyAI returned a business error",
                retryable=True,
                failure_kind="BUSINESS_ERROR",
                elapsed_ms=elapsed_ms,
            )
        data = payload.get("data")
        items = data.get("itemList") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise self._recorded_error(
                "FLIGGY_INVALID_RESPONSE",
                "FlyAI response itemList is missing",
                retryable=True,
                failure_kind="INVALID_RESPONSE",
                elapsed_ms=elapsed_ms,
            )
        self._runtime_registry.record_success("fliggy_flyai", elapsed_ms)
        logger.info(
            "flyai_cli_success command=%s elapsed_ms=%s item_count=%s response_hash=%s",
            command,
            elapsed_ms,
            len(items),
            response_hash,
        )
        return FlyAICommandResult(
            payload=payload,
            response_hash=response_hash,
            item_count=len(items),
            elapsed_ms=elapsed_ms,
        )

    def _recorded_error(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        failure_kind: RuntimeFailureKind,
        elapsed_ms: int | None,
        exit_code: int | None = None,
    ) -> FlyAIClientError:
        self._runtime_registry.record_failure(
            "fliggy_flyai",
            failure_kind=failure_kind,
            error_code=code,
            retryable=retryable,
            latency_ms=elapsed_ms,
        )
        return FlyAIClientError(
            code,
            message,
            retryable=retryable,
            failure_kind=failure_kind,
            exit_code=exit_code,
            elapsed_ms=elapsed_ms,
        )


def _validated_location(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _LOCATION_RE.fullmatch(normalized):
        raise FlyAIClientError("FLIGGY_INVALID_INPUT", f"{field_name} is invalid", retryable=False)
    return normalized


def _resolved_executable(executable: str) -> str:
    if os.name != "nt":
        return executable
    path = Path(executable)
    if path.suffix:
        return executable
    windows_shim = path.with_suffix(".cmd")
    return str(windows_shim) if windows_shim.is_file() else executable


def _certified_bundle_if_present(executable: str) -> Path | None:
    path = Path(executable)
    if path.parent.name != ".bin":
        return None
    package_root = path.parent.parent / "@fly-ai" / "flyai-cli"
    bundle = package_root / "dist" / "flyai-bundle.cjs"
    package_path = package_root / "package.json"
    if not bundle.is_file() or not package_path.is_file():
        raise FlyAIClientError(
            "FLIGGY_RUNTIME_NOT_CERTIFIED",
            "FlyAI locked package artifact is incomplete",
            retryable=False,
            failure_kind="EXECUTION_FAILED",
        )
    try:
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlyAIClientError(
            "FLIGGY_RUNTIME_NOT_CERTIFIED",
            "FlyAI locked package metadata is invalid",
            retryable=False,
            failure_kind="EXECUTION_FAILED",
        ) from exc
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if package_payload.get("version") != _CERTIFIED_CLI_VERSION or bundle_hash != _CERTIFIED_PATCHED_BUNDLE_SHA256:
        raise FlyAIClientError(
            "FLIGGY_RUNTIME_NOT_CERTIFIED",
            "FlyAI package version or bundle hash is not certified",
            retryable=False,
            failure_kind="EXECUTION_FAILED",
        )
    return bundle


def _runtime_command_prefix(executable: str, certified_bundle: Path | None) -> list[str]:
    if os.name != "nt" or certified_bundle is None:
        return [executable]
    node_executable = shutil.which("node")
    if not node_executable:
        raise FlyAIClientError(
            "FLIGGY_RUNTIME_NOT_CERTIFIED",
            "Node.js executable is required for the certified FlyAI runtime",
            retryable=False,
            failure_kind="EXECUTION_FAILED",
        )
    # The locked CLI uses WebAssembly internally. Disabling V8 background tasks
    # removes the Windows shutdown race while retaining the exact official bundle.
    return [node_executable, "--single-threaded", str(certified_bundle)]


def _validated_option(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _OPTION_RE.fullmatch(normalized):
        raise FlyAIClientError("FLIGGY_INVALID_INPUT", f"{field_name} is invalid", retryable=False)
    return normalized


def _validated_positive_int(value: int, field_name: str) -> int:
    if value <= 0:
        raise FlyAIClientError("FLIGGY_INVALID_INPUT", f"{field_name} is invalid", retryable=False)
    return value


def _validated_sort_type(value: int) -> int:
    if value not in range(1, 9):
        raise FlyAIClientError("FLIGGY_INVALID_INPUT", "sort_type is invalid", retryable=False)
    return value


def _monotonic_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def _is_fatal_process_exit(returncode: int, stderr: str) -> bool:
    unsigned_code = returncode & 0xFFFFFFFF
    if unsigned_code == 0xC0000409 or returncode < 0:
        return True
    normalized_stderr = stderr.lower()
    return any(
        marker in normalized_stderr
        for marker in (
            "uv_handle_closing",
            "uv_async_send",
            "assertion failed",
            "stack buffer overrun",
        )
    )
