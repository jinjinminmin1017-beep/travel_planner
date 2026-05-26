from __future__ import annotations

import json
import os
from pathlib import Path

from app.models.schemas import DataSourceConfig, DataSourceRuntimeStatus, now_timepoint

BASE_DIR = Path(__file__).resolve().parent


def load_data_source_configs(environment: str | None = None) -> list[DataSourceConfig]:
    env = (environment or os.getenv("APP_ENV", "DEV")).upper()
    path = BASE_DIR / f"data_sources.{env.lower()}.json"
    if not path.exists():
        path = BASE_DIR / "data_sources.dev.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    configs = [DataSourceConfig.model_validate(item) for item in payload]
    if env == "PROD":
        for config in configs:
            if config.source_type == "MOCK":
                raise ValueError("mock data sources are forbidden in PROD")
            if config.license_status != "APPROVED" or config.authority_level == "C":
                raise ValueError(f"data source {config.source_id} is not production approved")
    return configs


def runtime_statuses(environment: str | None = None) -> list[DataSourceRuntimeStatus]:
    statuses: list[DataSourceRuntimeStatus] = []
    for config in load_data_source_configs(environment):
        statuses.append(
            DataSourceRuntimeStatus(
                source_id=config.source_id,
                source_name=config.source_name,
                source_type=config.source_type,
                enabled=config.enabled,
                status="OK" if config.enabled else "DOWN",
                degraded=False,
                degraded_reason=None,
                last_success_at=now_timepoint() if config.enabled else None,
                last_failure_at=None,
                latest_failure=None,
                average_latency_ms=12,
                checked_at=now_timepoint(),
            )
        )
    return statuses
