from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.data_sources.config_loader import (
    DataSourceConfigurationError,
    load_flight_evidence_config,
)
from app.data_sources.flight_evidence_store import (
    FlightEvidenceConfig,
    FlightEvidencePersistenceError,
    FlightEvidenceStore,
)


def _store(tmp_path, *, required: bool = True) -> FlightEvidenceStore:
    return FlightEvidenceStore(
        FlightEvidenceConfig(
            backend="sqlite",
            path=tmp_path / "flight.sqlite3",
            required=required,
            hmac_key=b"unit-test-flight-evidence-key",
            success_retention_days=1,
            failure_retention_days=2,
        )
    )


def test_complete_429_exchange_is_exportable_and_redacted(tmp_path):
    store = _store(tmp_path)
    exchange_id = store.begin_exchange(
        source_id="airline_9c_public_query",
        stage="SEARCH",
        method="POST",
        url="https://example.test/search?token=plain-token&origin=SHA",
        headers={"Authorization": "Bearer request-secret", "Accept": "application/json"},
        body={"origin": "SHA", "destination": "DLC", "deviceId": "device-secret"},
        content_type="application/json",
        correlation_id="query-1",
    )
    store.record_response(
        exchange_id,
        status_code=429,
        headers={"Set-Cookie": "session=plain-cookie", "Content-Type": "application/json"},
        body=json.dumps({"code": 429, "message": "请求过于频繁", "token": "response-secret"}),
        content_type="application/json",
    )
    store.finish_exchange(
        exchange_id,
        outcome="RISK_CHALLENGE",
        error_code="FLIGHT_PROVIDER_RATE_LIMITED",
        business_code="429",
        message="请求过于频繁",
    )

    exported = store.export_exchange(exchange_id)
    assert exported["response_status"] == 429
    assert exported["business_code"] == "429"
    assert "请求过于频繁" in exported["response_body"]
    serialized = json.dumps(exported, ensure_ascii=False)
    assert "request-secret" not in serialized
    assert "plain-cookie" not in serialized
    assert "response-secret" not in serialized
    assert "device-secret" not in serialized
    assert serialized.count("[REDACTED:") >= 4
    assert len(exported["request_body_sha256"]) == 64
    assert len(exported["response_body_sha256"]) == 64


def test_parse_failure_keeps_complete_original_response_evidence(tmp_path):
    store = _store(tmp_path)
    exchange_id = store.begin_exchange(
        source_id="airline_qw_public_query",
        stage="SEARCH",
        method="POST",
        url="https://example.test/search",
        headers={},
        body={"origin": "TAO", "destination": "DLC"},
        content_type="application/json",
    )
    invalid_payload = '{"code":1,"message":"broken",'
    store.record_response(
        exchange_id,
        status_code=200,
        headers={"Content-Type": "application/json"},
        body=invalid_payload,
        content_type="application/json",
    )
    store.finish_exchange(
        exchange_id,
        outcome="PARSE_ERROR",
        error_code="FLIGHT_PROVIDER_PARSE_FAILED",
    )

    exported = store.export_exchange(exchange_id)
    assert exported["outcome"] == "PARSE_ERROR"
    assert exported["response_body"] == invalid_payload
    assert exported["response_body_length"] == len(invalid_payload.encode())


def test_required_mode_fails_closed_when_database_cannot_be_initialized(tmp_path):
    database_path = tmp_path / "database-is-a-directory"
    database_path.mkdir()
    with pytest.raises(FlightEvidencePersistenceError, match="FLIGHT_EVIDENCE_PERSISTENCE_FAILED"):
        FlightEvidenceStore(
            FlightEvidenceConfig(
                backend="sqlite",
                path=database_path,
                required=True,
                hmac_key=b"required-key",
            )
        )


def test_cleanup_uses_separate_success_and_failure_retention(tmp_path):
    store = _store(tmp_path)
    success_id = store.begin_exchange(
        source_id="airline_test",
        stage="SEARCH",
        method="GET",
        url="https://example.test",
        headers={},
        body=None,
        content_type=None,
    )
    store.finish_exchange(success_id, outcome="SUCCESS")
    failure_id = store.begin_exchange(
        source_id="airline_test",
        stage="SEARCH",
        method="GET",
        url="https://example.test",
        headers={},
        body=None,
        content_type=None,
    )
    store.finish_exchange(failure_id, outcome="HTTP_ERROR")
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with sqlite3.connect(store.config.path) as connection:
        connection.execute(
            "UPDATE flight_provider_exchanges SET started_at = ?",
            (old,),
        )
    assert store.cleanup_expired() == 2


def test_typed_config_requires_secret_when_evidence_is_required(tmp_path):
    with pytest.raises(DataSourceConfigurationError, match="HMAC_KEY"):
        load_flight_evidence_config(
            "PROD",
            environ={
                "APP_ENV": "PROD",
                "TRAVEL_FLIGHT_EVIDENCE_BACKEND": "sqlite",
                "TRAVEL_FLIGHT_EVIDENCE_PATH": str(tmp_path / "flight.sqlite3"),
                "TRAVEL_FLIGHT_EVIDENCE_REQUIRED": "true",
            },
        )
