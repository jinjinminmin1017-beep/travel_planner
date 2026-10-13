from __future__ import annotations

import json

import httpx
import pytest

from scripts.benchmark_rail_timetable_import import _legacy_projection, run_benchmark


def test_legacy_logical_bytes_match_each_full_document_serialization() -> None:
    key = "2026-10-13"
    payload = {
        "version": 1,
        "dates": {
            "2026-10-12": {"status": "ACTIVE", "completed_train_nos": ["old-1", "old-2"]},
            key: {"status": "STAGING", "discovery": {"services": {"fixture": {"name": "始发站"}}}},
        },
    }
    train_nos = ["short", "longer-number", "中文", "four"]
    projection = _legacy_projection(payload, key, train_nos)
    actual = 0
    for completed in range(1, len(train_nos) + 1):
        payload["dates"][key]["completed_train_nos"] = train_nos[:completed]
        actual += len(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
    assert projection["projected_logical_checkpoint_bytes"] == actual
    assert projection["physical_checkpoint_writes"] == 0


def test_offline_benchmark_imports_fixture_without_network_or_per_service_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*_args, **_kwargs):
        raise AssertionError("offline benchmark attempted network access")

    monkeypatch.setattr(httpx.Client, "request", reject_network)
    report = run_benchmark(
        services=7, historical_dates=2, stops=3, checkpoint_every=3, storage_batch_size=2
    )
    current = report["current_date_files_periodic_writes"]
    assert current["pipeline_summary"]["activated"] is True
    assert current["pipeline_summary"]["service_count"] == 7
    assert current["pipeline_summary"]["stop_count"] == 21
    assert current["fixture_detail_calls"] == 7
    assert current["actual_network_requests"] == 0
    assert current["sql_by_phase"]["upsert"]["count_statements"] == 0
    assert current["sql_by_phase"]["upsert"]["begin"] == 4
    assert current["sql_by_phase"]["activation"]["count_statements"] >= 3
    assert current["physical_checkpoint_bytes"] < report["legacy_full_document_per_service"]["projected_logical_checkpoint_bytes"]
    assert report["network_spacing_estimate"]["one_full_date_detail_seconds"] == 10.5
    assert report["temporary_files_removed"] is True
