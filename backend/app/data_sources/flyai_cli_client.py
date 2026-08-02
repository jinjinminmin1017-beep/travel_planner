from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger("app.flyai")

_LOCATION_RE = re.compile(r"^[A-Za-z0-9\u3400-\u9fff \-\u00b7]{1,80}$")
_OPTION_RE = re.compile(r"^[A-Za-z0-9\u3400-\u9fff ,\-\u00b7]{1,80}$")


class FlyAIClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.retryable = retryable


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
    ) -> None:
        if not api_key:
            raise FlyAIClientError("FLIGGY_API_KEY_MISSING", "FlyAI API key is missing", retryable=False)
        if not executable.strip():
            raise FlyAIClientError("FLIGGY_EXECUTABLE_MISSING", "FlyAI executable is missing", retryable=False)
        self._api_key = api_key
        self.executable = executable.strip()
        self.timeout_seconds = timeout_seconds
        self._runner = runner
        self._base_environment = dict(base_environment or os.environ)

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
        argv = [self.executable, command, *arguments]
        environment = dict(self._base_environment)
        environment["FLYAI_API_KEY"] = self._api_key
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
            raise FlyAIClientError("FLIGGY_TIMEOUT", "FlyAI CLI timed out", retryable=True) from exc
        except (OSError, UnicodeError) as exc:
            raise FlyAIClientError("FLIGGY_EXECUTION_FAILED", "FlyAI CLI could not be executed", retryable=True) from exc

        elapsed_ms = max(0, _monotonic_ms() - started_at)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        response_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        if completed.returncode != 0:
            logger.warning(
                "flyai_cli_failed command=%s exit_code=%s elapsed_ms=%s response_hash=%s",
                command,
                completed.returncode,
                elapsed_ms,
                response_hash,
            )
            raise FlyAIClientError("FLIGGY_NON_ZERO_EXIT", "FlyAI CLI returned a non-zero exit code", retryable=True)
        if stderr.strip():
            raise FlyAIClientError("FLIGGY_STDERR", "FlyAI CLI wrote unexpected stderr output", retryable=True)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise FlyAIClientError("FLIGGY_INVALID_JSON", "FlyAI CLI stdout is not one complete JSON object", retryable=True) from exc
        if not isinstance(payload, dict):
            raise FlyAIClientError("FLIGGY_INVALID_RESPONSE", "FlyAI CLI response must be a JSON object", retryable=True)
        status = payload.get("status")
        message = str(payload.get("message") or "")
        system_message = str(payload.get("systemMessage") or "")
        if "体验模式" in system_message or "experience mode" in system_message.lower():
            raise FlyAIClientError("FLIGGY_EXPERIENCE_MODE", "FlyAI response is limited to experience mode", retryable=False)
        if type(status) is not int or status != 0 or message.lower() != "success":
            business_signal = f"{message} {system_message}".lower()
            if any(marker in business_signal for marker in ("rate limit", "too many", "quota", "频率", "次数", "限制")):
                raise FlyAIClientError("FLIGGY_RATE_LIMITED", "FlyAI rate limit was reached", retryable=True)
            raise FlyAIClientError("FLIGGY_BUSINESS_ERROR", "FlyAI returned a business error", retryable=True)
        data = payload.get("data")
        items = data.get("itemList") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise FlyAIClientError("FLIGGY_INVALID_RESPONSE", "FlyAI response itemList is missing", retryable=True)
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


def _validated_location(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _LOCATION_RE.fullmatch(normalized):
        raise FlyAIClientError("FLIGGY_INVALID_INPUT", f"{field_name} is invalid", retryable=False)
    return normalized


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
