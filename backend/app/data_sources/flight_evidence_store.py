from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

logger = logging.getLogger("app.flight.evidence")

REDACTION_VERSION = "flight-redaction-v1"
PARSER_VERSION = "flight-exchange-v1"
FlightExchangeOutcome = Literal[
    "PENDING",
    "SUCCESS",
    "EMPTY",
    "HTTP_ERROR",
    "BUSINESS_ERROR",
    "PARSE_ERROR",
    "TIMEOUT",
    "CONNECT_ERROR",
    "RISK_CHALLENGE",
    "PERSISTENCE_ERROR",
]

_SENSITIVE_KEY = re.compile(
    r"(authorization|cookie|set-cookie|token|secret|signature|sign|device|fingerprint|"
    r"session|password|passwd|credential|api[-_]?key|private[-_]?key|encrypted_query)",
    re.IGNORECASE,
)
_PERSONAL_KEY = re.compile(
    r"(passenger|traveller|traveler|mobile|phone|email|identity|id[-_]?card|"
    r"passport|real[-_]?name|bank[-_]?card)",
    re.IGNORECASE,
)
_EXPORT_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/\-=]{8,}|"
    r"(?:authorization|cookie|set-cookie|token|secret|signature|api[-_]?key)"
    r"\s*[:=]\s*(?!\[REDACTED)[\"']?[a-z0-9._~+/\-=]{6,})"
)


class FlightEvidenceError(RuntimeError):
    pass


class FlightEvidencePersistenceError(FlightEvidenceError):
    pass


class FlightEvidenceExportRejected(FlightEvidenceError):
    pass


@dataclass(frozen=True)
class FlightEvidenceConfig:
    backend: Literal["sqlite", "disabled"] = "disabled"
    path: Path = Path("logs/flight_harvest.sqlite3")
    required: bool = False
    hmac_key: bytes | None = None
    success_retention_days: int = 90
    failure_retention_days: int = 180

    def validate(self) -> None:
        if self.required and self.backend != "sqlite":
            raise FlightEvidencePersistenceError(
                "FLIGHT_EVIDENCE_PERSISTENCE_FAILED: required evidence backend is disabled"
            )
        if self.required and not self.hmac_key:
            raise FlightEvidencePersistenceError(
                "FLIGHT_EVIDENCE_PERSISTENCE_FAILED: required evidence HMAC key is missing"
            )
        if self.success_retention_days < 1 or self.failure_retention_days < 1:
            raise FlightEvidencePersistenceError(
                "FLIGHT_EVIDENCE_PERSISTENCE_FAILED: retention days must be positive"
            )


@dataclass(frozen=True)
class StoredBody:
    compressed: bytes
    original_sha256: str
    redacted_sha256: str
    original_length: int
    redacted_text: str


class FlightEvidenceStore:
    def __init__(self, config: FlightEvidenceConfig) -> None:
        config.validate()
        self.config = config
        if config.backend == "sqlite":
            self._initialize()

    @property
    def enabled(self) -> bool:
        return self.config.backend == "sqlite"

    def begin_exchange(
        self,
        *,
        source_id: str,
        stage: str,
        method: str,
        url: str,
        headers: Mapping[str, object] | None,
        body: object | None,
        content_type: str | None,
        correlation_id: str | None = None,
    ) -> str:
        exchange_id = f"fltex_{uuid4().hex[:16]}"
        if not self.enabled:
            return exchange_id
        started_at = _utc_now()
        request_body = _store_body(body, content_type, self.config.hmac_key)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO flight_provider_exchanges(
                      exchange_id, source_id, stage, correlation_id, request_method,
                      request_url, request_headers_json, request_body_gzip,
                      request_body_sha256, request_redacted_sha256, request_body_length,
                      request_content_type, outcome, started_at, parser_version,
                      redaction_version, retention_class
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, 'FAILURE')
                    """,
                    (
                        exchange_id,
                        source_id,
                        stage,
                        correlation_id,
                        method.upper(),
                        redact_url(url, self.config.hmac_key),
                        json.dumps(redact_headers(headers or {}, self.config.hmac_key), ensure_ascii=False, sort_keys=True),
                        request_body.compressed,
                        request_body.original_sha256,
                        request_body.redacted_sha256,
                        request_body.original_length,
                        content_type or "",
                        started_at,
                        PARSER_VERSION,
                        REDACTION_VERSION,
                    ),
                )
        except Exception as exc:
            self._persistence_failure("begin", exchange_id, exc)
        logger.info(
            "flight_exchange_started exchange_id=%s source_id=%s stage=%s",
            exchange_id,
            source_id,
            stage,
        )
        return exchange_id

    def record_response(
        self,
        exchange_id: str,
        *,
        status_code: int,
        headers: Mapping[str, object] | None,
        body: object | None,
        content_type: str | None,
    ) -> None:
        if not self.enabled:
            return
        response_body = _store_body(body, content_type, self.config.hmac_key)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE flight_provider_exchanges
                    SET response_status = ?, response_headers_json = ?,
                        response_body_gzip = ?, response_body_sha256 = ?,
                        response_redacted_sha256 = ?, response_body_length = ?,
                        response_content_type = ?, response_received_at = ?
                    WHERE exchange_id = ?
                    """,
                    (
                        status_code,
                        json.dumps(redact_headers(headers or {}, self.config.hmac_key), ensure_ascii=False, sort_keys=True),
                        response_body.compressed,
                        response_body.original_sha256,
                        response_body.redacted_sha256,
                        response_body.original_length,
                        content_type or "",
                        _utc_now(),
                        exchange_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise FlightEvidencePersistenceError("exchange does not exist")
        except Exception as exc:
            self._persistence_failure("response", exchange_id, exc)

    def finish_exchange(
        self,
        exchange_id: str,
        *,
        outcome: FlightExchangeOutcome,
        error_code: str | None = None,
        business_code: str | None = None,
        message: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        completed_at = _utc_now()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT started_at FROM flight_provider_exchanges WHERE exchange_id = ?",
                    (exchange_id,),
                ).fetchone()
                if row is None:
                    raise FlightEvidencePersistenceError("exchange does not exist")
                duration_ms = max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(completed_at)
                            - datetime.fromisoformat(str(row[0]))
                        ).total_seconds()
                        * 1000
                    ),
                )
                connection.execute(
                    """
                    UPDATE flight_provider_exchanges
                    SET outcome = ?, error_code = ?, business_code = ?, outcome_message = ?,
                        completed_at = ?, duration_ms = ?, retention_class = ?
                    WHERE exchange_id = ?
                    """,
                    (
                        outcome,
                        error_code,
                        business_code,
                        _safe_outcome_message(message),
                        completed_at,
                        duration_ms,
                        "SUCCESS" if outcome in {"SUCCESS", "EMPTY"} else "FAILURE",
                        exchange_id,
                    ),
                )
        except Exception as exc:
            self._persistence_failure("finish", exchange_id, exc)
        logger.info(
            "flight_exchange_completed exchange_id=%s outcome=%s error_code=%s",
            exchange_id,
            outcome,
            error_code,
        )

    def export_exchange(self, exchange_id: str) -> dict[str, object]:
        if not self.enabled:
            raise FlightEvidenceError("flight evidence backend is disabled")
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM flight_provider_exchanges WHERE exchange_id = ?",
                (exchange_id,),
            ).fetchone()
        if row is None:
            raise FlightEvidenceError(f"exchange not found: {exchange_id}")
        result = dict(row)
        for prefix in ("request", "response"):
            compressed = result.pop(f"{prefix}_body_gzip", None)
            result[f"{prefix}_body"] = (
                gzip.decompress(compressed).decode("utf-8") if compressed is not None else None
            )
            headers = result.get(f"{prefix}_headers_json")
            result[f"{prefix}_headers"] = json.loads(headers) if headers else {}
            result.pop(f"{prefix}_headers_json", None)
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        if _EXPORT_SECRET_PATTERN.search(serialized):
            raise FlightEvidenceExportRejected(
                "flight evidence export rejected: possible plaintext secret"
            )
        return result

    def cleanup_expired(self, *, now: datetime | None = None, batch_size: int = 500) -> int:
        if not self.enabled:
            return 0
        reference = now or datetime.now(timezone.utc)
        success_cutoff = (reference - timedelta(days=self.config.success_retention_days)).isoformat()
        failure_cutoff = (reference - timedelta(days=self.config.failure_retention_days)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT exchange_id FROM flight_provider_exchanges
                WHERE (retention_class = 'SUCCESS' AND started_at < ?)
                   OR (retention_class = 'FAILURE' AND started_at < ?)
                ORDER BY started_at
                LIMIT ?
                """,
                (success_cutoff, failure_cutoff, max(1, batch_size)),
            ).fetchall()
            ids = [str(row[0]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM flight_provider_exchanges WHERE exchange_id IN ({placeholders})",
                    ids,
                )
        logger.info("flight_exchange_cleanup deleted_count=%s", len(ids))
        return len(ids)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.config.path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        self.config.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS flight_provider_exchanges (
                      exchange_id TEXT PRIMARY KEY,
                      source_id TEXT NOT NULL,
                      stage TEXT NOT NULL,
                      correlation_id TEXT,
                      request_method TEXT NOT NULL,
                      request_url TEXT NOT NULL,
                      request_headers_json TEXT NOT NULL,
                      request_body_gzip BLOB NOT NULL,
                      request_body_sha256 TEXT NOT NULL,
                      request_redacted_sha256 TEXT NOT NULL,
                      request_body_length INTEGER NOT NULL,
                      request_content_type TEXT,
                      response_status INTEGER,
                      response_headers_json TEXT,
                      response_body_gzip BLOB,
                      response_body_sha256 TEXT,
                      response_redacted_sha256 TEXT,
                      response_body_length INTEGER,
                      response_content_type TEXT,
                      outcome TEXT NOT NULL,
                      error_code TEXT,
                      business_code TEXT,
                      outcome_message TEXT,
                      started_at TEXT NOT NULL,
                      response_received_at TEXT,
                      completed_at TEXT,
                      duration_ms INTEGER,
                      parser_version TEXT NOT NULL,
                      redaction_version TEXT NOT NULL,
                      retention_class TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_flight_provider_exchanges_source_started
                    ON flight_provider_exchanges(source_id, started_at)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_flight_provider_exchanges_outcome_started
                    ON flight_provider_exchanges(outcome, started_at)
                    """
                )
        except Exception as exc:
            self._persistence_failure("initialize", "none", exc)

    def _persistence_failure(self, operation: str, exchange_id: str, exc: Exception) -> None:
        logger.error(
            "flight_exchange_persistence_failed operation=%s exchange_id=%s error_type=%s",
            operation,
            exchange_id,
            type(exc).__name__,
        )
        if self.config.required:
            raise FlightEvidencePersistenceError(
                "FLIGHT_EVIDENCE_PERSISTENCE_FAILED"
            ) from exc


def redact_headers(
    headers: Mapping[str, object],
    hmac_key: bytes | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        text = str(value)
        result[str(key)] = (
            _redacted_marker(str(key), text, hmac_key)
            if _is_sensitive_key(str(key))
            else text
        )
    return result


def redact_url(url: str, hmac_key: bytes | None) -> str:
    parsed = urlsplit(url)
    query = [
        (
            key,
            _redacted_marker(key, value, hmac_key)
            if _is_sensitive_key(key)
            else value,
        )
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
    )


def redact_body(body: object | None, content_type: str | None, hmac_key: bytes | None) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    elif isinstance(body, str):
        text = body
    else:
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)
    lowered_type = (content_type or "").lower()
    if isinstance(body, (dict, list)) or "json" in lowered_type:
        try:
            parsed = body if isinstance(body, (dict, list)) else json.loads(text)
            return json.dumps(
                _redact_structured(parsed, hmac_key),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            pass
    if "x-www-form-urlencoded" in lowered_type:
        values = parse_qsl(text, keep_blank_values=True)
        return urlencode(
            [
                (
                    key,
                    _redacted_marker(key, value, hmac_key)
                    if _is_sensitive_key(key)
                    else value,
                )
                for key, value in values
            ]
        )
    return _redact_text(text, hmac_key)


def _redact_structured(value: object, hmac_key: bytes | None) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                _redacted_marker(str(key), json.dumps(item, ensure_ascii=False, default=str), hmac_key)
                if _is_sensitive_key(str(key))
                else _redact_structured(item, hmac_key)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_structured(item, hmac_key) for item in value]
    if isinstance(value, str):
        return _redact_text(value, hmac_key)
    return value


def _redact_text(text: str, hmac_key: bytes | None) -> str:
    patterns = [
        re.compile(
            r"(?i)\b(authorization|cookie|set-cookie|token|secret|signature|api[-_]?key)"
            r"\b\s*[:=]\s*([\"']?)([^,\s;\"'<>]+)\2"
        ),
        re.compile(r"(?i)\bbearer\s+([a-z0-9._~+/\-=]+)"),
        re.compile(r"\b1[3-9]\d{9}\b"),
        re.compile(r"\b[A-Z]\d{7,8}\b", re.IGNORECASE),
    ]
    result = text

    def replace_assignment(match: re.Match[str]) -> str:
        key = match.group(1)
        value = match.group(3)
        return f"{key}={_redacted_marker(key, value, hmac_key)}"

    result = patterns[0].sub(replace_assignment, result)
    result = patterns[1].sub(
        lambda match: f"Bearer {_redacted_marker('bearer', match.group(1), hmac_key)}",
        result,
    )
    result = patterns[2].sub(
        lambda match: _redacted_marker("phone", match.group(0), hmac_key),
        result,
    )
    result = patterns[3].sub(
        lambda match: _redacted_marker("identity", match.group(0), hmac_key),
        result,
    )
    return result


def _store_body(
    body: object | None,
    content_type: str | None,
    hmac_key: bytes | None,
) -> StoredBody:
    if body is None:
        original = b""
    elif isinstance(body, bytes):
        original = body
    elif isinstance(body, str):
        original = body.encode("utf-8")
    else:
        original = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    redacted_text = redact_body(body, content_type, hmac_key)
    redacted = redacted_text.encode("utf-8")
    return StoredBody(
        compressed=gzip.compress(redacted),
        original_sha256=hashlib.sha256(original).hexdigest(),
        redacted_sha256=hashlib.sha256(redacted).hexdigest(),
        original_length=len(original),
        redacted_text=redacted_text,
    )


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key) or _PERSONAL_KEY.search(key))


def _redacted_marker(kind: str, value: str, hmac_key: bytes | None) -> str:
    digest = hmac.new(
        hmac_key or b"flight-evidence-local-redaction-only",
        value.encode("utf-8", errors="replace"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"[REDACTED:type={kind.lower()},len={len(value)},hmac={digest}]"


def _safe_outcome_message(message: str | None) -> str | None:
    if not message:
        return None
    return _redact_text(message[:1000], None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
