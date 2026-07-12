from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from app.models.schemas import DataSourceConfig, DataSourceRuntimeStatus, now_timepoint

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2]
_ENV_LOADED = False

REQUIRED_SECRET_ENVS = {
    "amap_route": ("AMAP_WEB_SERVICE_KEY", "AMAP_API_KEY"),
    "baidu_map_route": ("BAIDU_MAP_AK", "BAIDU_MAP_API_KEY"),
    "osrm_route": (),
    "nominatim_geocode": (),
    "amap_uri_redirect": (),
    "baidu_uri_redirect": (),
    "airline_mu_public_query": (),
    "airline_cz_public_query": (),
    "airline_sc_public_query": (),
    "opensky_states": (),
    "variflight_status": ("VARIFLIGHT_API_KEY",),
    "rail_12306_public_query": (),
    "open_meteo_forecast": (),
    "airline_official_redirect": (),
    "rail_12306_redirect": (),
    "real_llm": ("OPENAI_API_KEY", "LLM_API_KEY"),
}
PUBLIC_AIRLINE_QUERY_SOURCE_IDS = {
    "airline_mu_public_query",
    "airline_cz_public_query",
    "airline_sc_public_query",
}
PUBLIC_AIRLINE_ALLOWED_HOSTS = {
    "airline_mu_public_query": ("ceair.com",),
    "airline_cz_public_query": ("csair.com",),
    "airline_sc_public_query": ("sda.cn",),
}


def load_project_env(path: Path | None = None) -> None:
    global _ENV_LOADED
    if _ENV_LOADED and path is None:
        return
    env_path = path or PROJECT_ROOT / ".env"
    _ENV_LOADED = True
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _env_flag(name: str) -> bool | None:
    load_project_env()
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    load_project_env()
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return int(value)


def _source_env_name(source_id: str, suffix: str) -> str:
    return f"TRAVEL_SOURCE_{source_id.upper()}_{suffix}"


def _apply_env_overrides(config: DataSourceConfig) -> DataSourceConfig:
    updates = {}
    enabled = _env_flag(_source_env_name(config.source_id, "ENABLED"))
    if enabled is not None:
        updates["enabled"] = enabled
    qps_limit = _env_int(_source_env_name(config.source_id, "QPS_LIMIT"))
    if qps_limit is not None:
        updates["qps_limit"] = qps_limit
    license_status = os.getenv(_source_env_name(config.source_id, "LICENSE_STATUS"))
    if license_status:
        updates["license_status"] = license_status
    commercial_allowed = _env_flag(_source_env_name(config.source_id, "COMMERCIAL_ALLOWED"))
    if commercial_allowed is not None:
        updates["commercial_allowed"] = commercial_allowed
    return config.model_copy(update=updates) if updates else config


def required_secret_envs(source_id: str) -> tuple[str, ...]:
    return REQUIRED_SECRET_ENVS.get(source_id, ())


def public_airline_allowed_hosts(source_id: str) -> tuple[str, ...]:
    return PUBLIC_AIRLINE_ALLOWED_HOSTS.get(source_id, ())


def public_airline_base_url_allowed(source_id: str, base_url: str | None) -> bool:
    if not base_url:
        return False
    parsed = urlparse(base_url)
    if parsed.scheme.lower() != "https":
        return False
    hostname = (parsed.hostname or "").lower().strip(".")
    return _host_matches_allowed_hosts(hostname, public_airline_allowed_hosts(source_id))


def _host_matches_allowed_hosts(hostname: str, allowed_hosts: tuple[str, ...]) -> bool:
    for allowed_host in allowed_hosts:
        normalized = allowed_host.lower().strip(".")
        if hostname == normalized or hostname.endswith(f".{normalized}"):
            return True
    return False


def has_required_secret(source_id: str) -> bool:
    load_project_env()
    secrets = required_secret_envs(source_id)
    return not secrets or any(os.getenv(name) for name in secrets)


def load_data_source_configs(environment: str | None = None) -> list[DataSourceConfig]:
    load_project_env()
    env = (environment or os.getenv("APP_ENV", "DEV")).upper()
    path = BASE_DIR / f"data_sources.{env.lower()}.json"
    if not path.exists():
        path = BASE_DIR / "data_sources.dev.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    configs = [_apply_env_overrides(DataSourceConfig.model_validate(item)) for item in payload]
    if env == "PROD":
        validate_production_data_source_configs(configs)
    return configs


def validate_production_data_source_configs(configs: list[DataSourceConfig]) -> None:
    for config in configs:
        if config.enabled and config.license_status != "APPROVED":
            raise ValueError(f"data source {config.source_id} is enabled but not production approved")
        if config.enabled and config.authority_level == "C":
            raise ValueError(f"data source {config.source_id} is enabled with unsupported production authority level C")
        if config.enabled and config.commercial_allowed and config.license_status != "APPROVED":
            raise ValueError(f"data source {config.source_id} allows commercial usage without approval")


def runtime_statuses(environment: str | None = None) -> list[DataSourceRuntimeStatus]:
    statuses: list[DataSourceRuntimeStatus] = []
    for config in load_data_source_configs(environment):
        missing_secret = config.enabled and not has_required_secret(config.source_id)
        public_airline_base_url = os.getenv(_source_env_name(config.source_id, "BASE_URL"))
        missing_public_airline_base_url = config.enabled and config.source_id in PUBLIC_AIRLINE_QUERY_SOURCE_IDS and not public_airline_base_url
        invalid_public_airline_base_url = config.enabled and config.source_id in PUBLIC_AIRLINE_QUERY_SOURCE_IDS and bool(public_airline_base_url) and not public_airline_base_url_allowed(config.source_id, public_airline_base_url)
        pending_license = config.enabled and config.license_status != "APPROVED"
        degraded = missing_secret or missing_public_airline_base_url or invalid_public_airline_base_url or pending_license
        if missing_secret:
            degraded_reason = "required API credential environment variable is missing"
        elif missing_public_airline_base_url:
            degraded_reason = "official airline public query base URL is missing"
        elif invalid_public_airline_base_url:
            degraded_reason = "official airline public query base URL is outside the source allowlist"
        elif pending_license:
            degraded_reason = "data source license is not approved"
        else:
            degraded_reason = None
        health_status = "DEGRADED" if degraded else ("OK" if config.enabled else "DISABLED")
        statuses.append(
            DataSourceRuntimeStatus(
                source_id=config.source_id,
                source_name=config.source_name,
                source_type=config.source_type,
                enabled=config.enabled,
                health_status=health_status,
                degraded_reason=degraded_reason,
                authority_level=config.authority_level,
                license_status=config.license_status,
                commercial_allowed=config.commercial_allowed,
                last_success_at=now_timepoint() if config.enabled and not degraded else None,
                last_failure_at=now_timepoint() if degraded else None,
                latest_failure=None,
                average_latency_ms=12,
                checked_at=now_timepoint(),
            )
        )
    return statuses
