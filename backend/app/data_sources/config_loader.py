from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models.schemas import DataSourceConfig, DataSourceRuntimeStatus, DataSourceType, now_timepoint

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2]
_ENV_LOADED = False
_SETTINGS_SNAPSHOTS: dict[str, "DataSourceSettingsSnapshot"] = {}

LicenseStatus = Literal["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"]
AuthorityLevel = Literal["S", "A", "B", "C"]
EnvironmentName = Literal["DEV", "TEST", "PROD"]


class DataSourceConfigurationError(ValueError):
    """A fail-closed configuration error that never includes secret values."""


@dataclass(frozen=True)
class SourceDefinition:
    source_name: str
    source_type: DataSourceType
    authority_level: AuthorityLevel
    sla_level: str
    fallback_source_id: str | None = None


SOURCE_DEFINITIONS: dict[str, SourceDefinition] = {
    "internal_calc": SourceDefinition("Internal Deterministic Calculator", DataSourceType.INTERNAL_CALCULATION, "B", "INTERNAL"),
    "amap_route": SourceDefinition("AMap Route Planning API", DataSourceType.MAP, "A", "PENDING_REVIEW", "baidu_map_route"),
    "baidu_map_route": SourceDefinition("Baidu Map Route Planning API", DataSourceType.MAP, "A", "PENDING_REVIEW"),
    "amap_geocode": SourceDefinition("AMap Address Geocoding API", DataSourceType.MAP, "A", "PENDING_REVIEW", "amap_place_search"),
    "amap_place_search": SourceDefinition("AMap Place Search API", DataSourceType.MAP, "A", "PENDING_REVIEW", "nominatim_geocode"),
    "osrm_route": SourceDefinition("OSRM Route Service", DataSourceType.MAP, "B", "PUBLIC_DEMO_READ_ONLY"),
    "nominatim_geocode": SourceDefinition("Nominatim Search API", DataSourceType.MAP, "B", "PUBLIC_READ_ONLY_RATE_LIMITED"),
    "amap_uri_redirect": SourceDefinition("AMap URI Redirect", DataSourceType.MAP, "A", "REDIRECT_ONLY", "baidu_uri_redirect"),
    "baidu_uri_redirect": SourceDefinition("Baidu URI Redirect", DataSourceType.MAP, "A", "PENDING_REVIEW"),
    "opensky_states": SourceDefinition("OpenSky Network States API", DataSourceType.FLIGHT, "B", "PUBLIC_READ_ONLY_RATE_LIMITED"),
    "open_meteo_forecast": SourceDefinition("Open-Meteo Forecast API", DataSourceType.WEATHER, "B", "PUBLIC_READ_ONLY_RATE_LIMITED"),
    "airline_official_redirect": SourceDefinition("Airline Official Redirect", DataSourceType.FLIGHT, "A", "REDIRECT_ONLY"),
    "rail_12306_redirect": SourceDefinition("12306 Official Redirect", DataSourceType.RAIL, "S", "REDIRECT_ONLY"),
    "rail_12306_public_query": SourceDefinition("12306 Public Ticket Query", DataSourceType.RAIL, "S", "PUBLIC_ANONYMOUS_QUERY"),
    "real_llm": SourceDefinition("Real LLM Provider", DataSourceType.LLM, "A", "DISABLED_BY_DEFAULT"),
}


class DataSourceSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    adapter: str
    source_name: str
    source_type: DataSourceType
    authority_level: AuthorityLevel
    environment: EnvironmentName
    license_status: LicenseStatus
    commercial_allowed: bool
    enabled: bool
    qps_limit: int = Field(default=0, ge=0)
    sla_level: str
    fallback_source_id: str | None = None

    @model_validator(mode="after")
    def validate_common_enabled_fields(self) -> "DataSourceSettings":
        if self.commercial_allowed and self.license_status != "APPROVED":
            raise ValueError("COMMERCIAL_ALLOWED")
        return self

    def to_runtime_config(self) -> DataSourceConfig:
        return DataSourceConfig(
            source_id=self.source_id,
            source_name=self.source_name,
            source_type=self.source_type,
            authority_level=self.authority_level,
            environment=self.environment,
            license_status=self.license_status,
            commercial_allowed=self.commercial_allowed,
            enabled=self.enabled,
            qps_limit=self.qps_limit,
            sla_level=self.sla_level,
            fallback_source_id=self.fallback_source_id,
            last_checked_at=None,
        )


class InternalSourceSettings(DataSourceSettings):
    pass


class RedirectSourceSettings(DataSourceSettings):
    pass


class HttpSourceSettings(DataSourceSettings):
    base_url: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def validate_http_fields(self) -> "HttpSourceSettings":
        if self.enabled and self.qps_limit <= 0:
            raise ValueError("QPS_LIMIT")
        if self.enabled and not self.base_url:
            raise ValueError("BASE_URL")
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("BASE_URL")
            if self.allowed_hosts and not _host_matches_allowed_hosts(parsed.hostname, self.allowed_hosts):
                raise ValueError("BASE_URL/ALLOWED_HOSTS")
        return self


class CredentialedHttpSourceSettings(HttpSourceSettings):
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_api_key(self) -> "CredentialedHttpSourceSettings":
        if self.enabled and self.api_key is None:
            raise ValueError("API_KEY")
        return self


class RailSourceSettings(HttpSourceSettings):
    user_agent: str | None = None
    cache_ttl_seconds: int = Field(default=0, ge=0)
    min_interval_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_rail_fields(self) -> "RailSourceSettings":
        if self.enabled and not self.user_agent:
            raise ValueError("USER_AGENT")
        return self


class NominatimSourceSettings(HttpSourceSettings):
    user_agent: str | None = None

    @model_validator(mode="after")
    def validate_user_agent(self) -> "NominatimSourceSettings":
        if self.enabled and not self.user_agent:
            raise ValueError("USER_AGENT")
        return self


class RealLlmSourceSettings(CredentialedHttpSourceSettings):
    model: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    thinking_disabled: bool = True

    @model_validator(mode="after")
    def validate_llm_fields(self) -> "RealLlmSourceSettings":
        if self.enabled and not self.model:
            raise ValueError("MODEL")
        return self


ADAPTER_SETTINGS_MODELS: dict[str, type[DataSourceSettings]] = {
    "internal_calculation": InternalSourceSettings,
    "amap_route": CredentialedHttpSourceSettings,
    "baidu_map_route": CredentialedHttpSourceSettings,
    "amap_geocode": CredentialedHttpSourceSettings,
    "amap_place_search": CredentialedHttpSourceSettings,
    "osrm_route": HttpSourceSettings,
    "nominatim_geocode": NominatimSourceSettings,
    "amap_uri_redirect": RedirectSourceSettings,
    "baidu_uri_redirect": RedirectSourceSettings,
    "opensky_states": HttpSourceSettings,
    "open_meteo_forecast": HttpSourceSettings,
    "airline_official_redirect": RedirectSourceSettings,
    "rail_12306_redirect": RedirectSourceSettings,
    "rail_12306_public_query": RailSourceSettings,
    "real_llm": RealLlmSourceSettings,
}

COMMON_ENV_SUFFIXES = frozenset({"ADAPTER", "ENABLED", "LICENSE_STATUS", "COMMERCIAL_ALLOWED"})
HTTP_ENV_SUFFIXES = COMMON_ENV_SUFFIXES | frozenset(
    {"QPS_LIMIT", "BASE_URL", "ALLOWED_HOSTS", "TIMEOUT_SECONDS"}
)
CREDENTIALED_HTTP_ENV_SUFFIXES = HTTP_ENV_SUFFIXES | frozenset({"API_KEY"})
NOMINATIM_ENV_SUFFIXES = HTTP_ENV_SUFFIXES | frozenset({"USER_AGENT"})
RAIL_ENV_SUFFIXES = HTTP_ENV_SUFFIXES | frozenset(
    {"USER_AGENT", "CACHE_TTL_SECONDS", "MIN_INTERVAL_SECONDS"}
)
REAL_LLM_ENV_SUFFIXES = CREDENTIALED_HTTP_ENV_SUFFIXES | frozenset(
    {"MODEL", "MAX_TOKENS", "THINKING_DISABLED"}
)
ADAPTER_ENV_SUFFIXES: dict[str, frozenset[str]] = {
    "internal_calculation": COMMON_ENV_SUFFIXES,
    "amap_route": CREDENTIALED_HTTP_ENV_SUFFIXES,
    "baidu_map_route": CREDENTIALED_HTTP_ENV_SUFFIXES,
    "amap_geocode": CREDENTIALED_HTTP_ENV_SUFFIXES,
    "amap_place_search": CREDENTIALED_HTTP_ENV_SUFFIXES,
    "osrm_route": HTTP_ENV_SUFFIXES,
    "nominatim_geocode": NOMINATIM_ENV_SUFFIXES,
    "amap_uri_redirect": COMMON_ENV_SUFFIXES,
    "baidu_uri_redirect": COMMON_ENV_SUFFIXES,
    "opensky_states": HTTP_ENV_SUFFIXES,
    "open_meteo_forecast": HTTP_ENV_SUFFIXES,
    "airline_official_redirect": COMMON_ENV_SUFFIXES,
    "rail_12306_redirect": COMMON_ENV_SUFFIXES,
    "rail_12306_public_query": RAIL_ENV_SUFFIXES,
    "real_llm": REAL_LLM_ENV_SUFFIXES,
}
ALL_ENV_SUFFIXES = frozenset().union(*ADAPTER_ENV_SUFFIXES.values())
REQUIRED_COMMON_SUFFIXES = tuple(sorted(COMMON_ENV_SUFFIXES))


class DataSourceSettingsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    environment: EnvironmentName
    sources: tuple[DataSourceSettings, ...]

    def get(self, source_id: str) -> DataSourceSettings | None:
        normalized = source_id.strip().lower()
        return next((source for source in self.sources if source.source_id == normalized), None)

    def by_adapter(self, adapter: str) -> tuple[DataSourceSettings, ...]:
        return tuple(source for source in self.sources if source.adapter == adapter)


def load_project_env(path: Path | None = None) -> None:
    global _ENV_LOADED
    if _ENV_LOADED and path is None:
        return
    env_path = path or PROJECT_ROOT / ".env"
    _ENV_LOADED = True
    reset_data_source_settings_cache()
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


def reset_data_source_settings_cache() -> None:
    _SETTINGS_SNAPSHOTS.clear()


def load_data_source_settings(
    environment: str | None = None,
    *,
    force_reload: bool = False,
    environ: Mapping[str, str] | None = None,
) -> DataSourceSettingsSnapshot:
    if environ is None:
        load_project_env()
        values: Mapping[str, str] = os.environ
    else:
        values = environ
        force_reload = True
    env = _parse_environment(environment or values.get("APP_ENV", "DEV"))
    if not force_reload and env in _SETTINGS_SNAPSHOTS:
        return _SETTINGS_SNAPSHOTS[env]
    snapshot = _parse_settings_snapshot(values, env)
    if environ is None:
        _SETTINGS_SNAPSHOTS[env] = snapshot
    return snapshot


def load_data_source_configs(environment: str | None = None) -> list[DataSourceConfig]:
    return [source.to_runtime_config() for source in load_data_source_settings(environment).sources]


def get_data_source_settings(source_id: str, environment: str | None = None) -> DataSourceSettings | None:
    return load_data_source_settings(environment).get(source_id)


def required_secret_envs(source_id: str) -> tuple[str, ...]:
    source = get_data_source_settings(source_id)
    if isinstance(source, (CredentialedHttpSourceSettings, RealLlmSourceSettings)):
        return (_source_env_name(source_id, "API_KEY"),)
    return ()


def has_required_secret(source_id: str, environment: str | None = None) -> bool:
    source = get_data_source_settings(source_id, environment)
    if source is None:
        return False
    return not isinstance(source, CredentialedHttpSourceSettings) or source.api_key is not None


def secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def validate_production_data_source_configs(configs: list[DataSourceConfig]) -> None:
    for config in configs:
        if config.enabled and config.license_status != "APPROVED":
            raise DataSourceConfigurationError(f"{config.source_id}: LICENSE_STATUS must be APPROVED in PROD")
        if config.enabled and config.authority_level == "C":
            raise DataSourceConfigurationError(f"{config.source_id}: AUTHORITY_LEVEL C is not allowed in PROD")
        if config.enabled and config.commercial_allowed and config.license_status != "APPROVED":
            raise DataSourceConfigurationError(f"{config.source_id}: COMMERCIAL_ALLOWED requires APPROVED")


def runtime_statuses(environment: str | None = None) -> list[DataSourceRuntimeStatus]:
    snapshot = load_data_source_settings(environment)
    statuses: list[DataSourceRuntimeStatus] = []
    for source in snapshot.sources:
        degraded_reason: str | None = None
        if source.enabled and source.license_status != "APPROVED":
            degraded_reason = "data source license is not approved"
        health_status = "DEGRADED" if degraded_reason else ("OK" if source.enabled else "DISABLED")
        statuses.append(
            DataSourceRuntimeStatus(
                source_id=source.source_id,
                source_name=source.source_name,
                source_type=source.source_type,
                enabled=source.enabled,
                health_status=health_status,
                degraded_reason=degraded_reason,
                authority_level=source.authority_level,
                license_status=source.license_status,
                commercial_allowed=source.commercial_allowed,
                last_success_at=now_timepoint() if source.enabled and not degraded_reason else None,
                last_failure_at=now_timepoint() if degraded_reason else None,
                latest_failure=None,
                average_latency_ms=None,
                checked_at=now_timepoint(),
            )
        )
    return statuses


def registered_source_env_keys(environ: Mapping[str, str]) -> set[str]:
    source_ids = _parse_source_ids(environ.get("TRAVEL_DATA_SOURCE_IDS"))
    keys = {"TRAVEL_DATA_SOURCE_IDS"}
    for source_id in source_ids:
        adapter = environ.get(_source_env_name(source_id, "ADAPTER"), "").strip().lower()
        for suffix in ADAPTER_ENV_SUFFIXES.get(adapter, COMMON_ENV_SUFFIXES):
            keys.add(_source_env_name(source_id, suffix))
    return keys


def expected_source_env_suffixes(adapter: str) -> frozenset[str]:
    return ADAPTER_ENV_SUFFIXES.get(adapter.strip().lower(), frozenset())


def _parse_settings_snapshot(values: Mapping[str, str], environment: EnvironmentName) -> DataSourceSettingsSnapshot:
    source_ids = _parse_source_ids(values.get("TRAVEL_DATA_SOURCE_IDS"))
    _validate_unknown_source_keys(values, source_ids)
    sources = tuple(_parse_source_settings(source_id, values, environment) for source_id in source_ids)
    if environment == "PROD":
        validate_production_data_source_configs([source.to_runtime_config() for source in sources])
    return DataSourceSettingsSnapshot(environment=environment, sources=sources)


def _parse_source_settings(
    source_id: str,
    values: Mapping[str, str],
    environment: EnvironmentName,
) -> DataSourceSettings:
    definition = SOURCE_DEFINITIONS.get(source_id)
    if definition is None:
        raise DataSourceConfigurationError(f"{source_id}: source_id is not registered in code")
    raw: dict[str, str] = {}
    for suffix in ALL_ENV_SUFFIXES:
        value = values.get(_source_env_name(source_id, suffix))
        if value is not None and value.strip() != "":
            raw[suffix] = value.strip()
    missing = [suffix for suffix in REQUIRED_COMMON_SUFFIXES if suffix not in raw]
    if missing:
        raise DataSourceConfigurationError(f"{source_id}: missing keys {', '.join(_source_env_name(source_id, item) for item in missing)}")
    adapter = raw["ADAPTER"].strip().lower()
    model = ADAPTER_SETTINGS_MODELS.get(adapter)
    if model is None:
        raise DataSourceConfigurationError(f"{source_id}: unknown adapter key {_source_env_name(source_id, 'ADAPTER')}")
    allowed_suffixes = ADAPTER_ENV_SUFFIXES[adapter]
    configured_suffixes = {
        suffix for suffix in ALL_ENV_SUFFIXES if _source_env_name(source_id, suffix) in values
    }
    unexpected = sorted(configured_suffixes - allowed_suffixes)
    if unexpected:
        raise DataSourceConfigurationError(
            f"{source_id}: unsupported keys "
            f"{', '.join(_source_env_name(source_id, suffix) for suffix in unexpected)}"
        )
    try:
        payload = {
            "source_id": source_id,
            "adapter": adapter,
            "source_name": definition.source_name,
            "source_type": definition.source_type,
            "authority_level": definition.authority_level,
            "environment": environment,
            "license_status": _parse_enum(source_id, "LICENSE_STATUS", raw["LICENSE_STATUS"], {"APPROVED", "PENDING_REVIEW", "NOT_APPROVED"}),
            "commercial_allowed": _parse_bool(source_id, "COMMERCIAL_ALLOWED", raw["COMMERCIAL_ALLOWED"]),
            "enabled": _parse_bool(source_id, "ENABLED", raw["ENABLED"]),
            "qps_limit": _parse_int(source_id, "QPS_LIMIT", raw.get("QPS_LIMIT", "0"), minimum=0),
            "sla_level": definition.sla_level,
            "fallback_source_id": definition.fallback_source_id,
        }
        if issubclass(model, HttpSourceSettings):
            payload.update(
                {
                    "base_url": raw.get("BASE_URL"),
                    "allowed_hosts": _parse_csv(raw.get("ALLOWED_HOSTS"), lower=True),
                    "timeout_seconds": _parse_float(
                        source_id,
                        "TIMEOUT_SECONDS",
                        raw.get("TIMEOUT_SECONDS", "10"),
                        minimum=0.001,
                    ),
                }
            )
        if issubclass(model, CredentialedHttpSourceSettings):
            payload["api_key"] = SecretStr(raw["API_KEY"]) if raw.get("API_KEY") else None
        if issubclass(model, (NominatimSourceSettings, RailSourceSettings)):
            payload["user_agent"] = raw.get("USER_AGENT")
        if issubclass(model, RailSourceSettings):
            payload["cache_ttl_seconds"] = _parse_int(
                source_id,
                "CACHE_TTL_SECONDS",
                raw.get("CACHE_TTL_SECONDS", "0"),
                minimum=0,
            )
            payload["min_interval_seconds"] = _optional_float(
                source_id,
                "MIN_INTERVAL_SECONDS",
                raw.get("MIN_INTERVAL_SECONDS"),
                minimum=0,
            )
        if issubclass(model, RealLlmSourceSettings):
            payload.update(
                {
                    "model": raw.get("MODEL"),
                    "max_tokens": _optional_int(
                        source_id,
                        "MAX_TOKENS",
                        raw.get("MAX_TOKENS"),
                        minimum=1,
                    ),
                    "thinking_disabled": _parse_bool(
                        source_id,
                        "THINKING_DISABLED",
                        raw.get("THINKING_DISABLED", "true"),
                    ),
                }
            )
        _validate_adapter_payload(source_id, model, payload)
        return model.model_validate(payload)
    except DataSourceConfigurationError:
        raise
    except Exception as exc:
        field_names = sorted(
            {
                str((item.get("loc") or ("configuration",))[-1]).upper()
                for item in getattr(exc, "errors", lambda: [])()
            }
        )
        keys = ", ".join(_source_env_name(source_id, field) for field in field_names) if field_names else "source settings"
        raise DataSourceConfigurationError(f"{source_id}: invalid configuration keys {keys}") from None


def _validate_adapter_payload(
    source_id: str,
    model: type[DataSourceSettings],
    payload: dict[str, object],
) -> None:
    enabled = bool(payload["enabled"])
    qps_limit = int(payload["qps_limit"])
    if enabled and issubclass(model, HttpSourceSettings) and qps_limit <= 0:
        raise DataSourceConfigurationError(
            f"{source_id}: invalid integer key {_source_env_name(source_id, 'QPS_LIMIT')}"
        )
    if payload["commercial_allowed"] and payload["license_status"] != "APPROVED":
        raise DataSourceConfigurationError(
            f"{source_id}: invalid boolean key {_source_env_name(source_id, 'COMMERCIAL_ALLOWED')}"
        )
    base_url = payload.get("base_url")
    allowed_hosts = payload.get("allowed_hosts") or ()
    if base_url:
        parsed = urlparse(str(base_url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DataSourceConfigurationError(
                f"{source_id}: invalid URL key {_source_env_name(source_id, 'BASE_URL')}"
            )
        if allowed_hosts and not _host_matches_allowed_hosts(parsed.hostname, allowed_hosts):
            raise DataSourceConfigurationError(
                f"{source_id}: invalid host keys {_source_env_name(source_id, 'BASE_URL')}, "
                f"{_source_env_name(source_id, 'ALLOWED_HOSTS')}"
            )
    if not enabled:
        return
    missing: list[str] = []
    if issubclass(model, HttpSourceSettings) and not base_url:
        missing.append("BASE_URL")
    if issubclass(model, CredentialedHttpSourceSettings) and payload.get("api_key") is None:
        missing.append("API_KEY")
    if issubclass(model, (NominatimSourceSettings, RailSourceSettings)) and not payload.get("user_agent"):
        missing.append("USER_AGENT")
    if issubclass(model, RealLlmSourceSettings) and not payload.get("model"):
        missing.append("MODEL")
    if missing:
        raise DataSourceConfigurationError(
            f"{source_id}: missing keys {', '.join(_source_env_name(source_id, item) for item in missing)}"
        )


def _parse_source_ids(value: str | None) -> tuple[str, ...]:
    if not value or not value.strip():
        raise DataSourceConfigurationError("missing key TRAVEL_DATA_SOURCE_IDS")
    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not items:
        raise DataSourceConfigurationError("TRAVEL_DATA_SOURCE_IDS is empty")
    duplicates = sorted({item for item in items if items.count(item) > 1})
    if duplicates:
        raise DataSourceConfigurationError(f"TRAVEL_DATA_SOURCE_IDS contains duplicate source_id keys: {', '.join(duplicates)}")
    invalid = [item for item in items if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", item)]
    if invalid:
        raise DataSourceConfigurationError("TRAVEL_DATA_SOURCE_IDS contains invalid source_id keys")
    return items


def _validate_unknown_source_keys(values: Mapping[str, str], source_ids: tuple[str, ...]) -> None:
    prefixes = {source_id: f"TRAVEL_SOURCE_{source_id.upper()}_" for source_id in source_ids}
    unknown: list[str] = []
    for key in values:
        if not key.startswith("TRAVEL_SOURCE_"):
            continue
        match = next(((source_id, prefix) for source_id, prefix in prefixes.items() if key.startswith(prefix)), None)
        if match is None:
            unknown.append(key)
            continue
        suffix = key[len(match[1]) :]
        if suffix not in ALL_ENV_SUFFIXES:
            unknown.append(key)
    if unknown:
        raise DataSourceConfigurationError(f"unknown data source configuration keys: {', '.join(sorted(unknown))}")


def _source_env_name(source_id: str, suffix: str) -> str:
    return f"TRAVEL_SOURCE_{source_id.upper()}_{suffix}"


def _parse_environment(value: str) -> EnvironmentName:
    normalized = value.strip().upper()
    if normalized not in {"DEV", "TEST", "PROD"}:
        raise DataSourceConfigurationError("invalid key APP_ENV")
    return normalized  # type: ignore[return-value]


def _parse_bool(source_id: str, suffix: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise DataSourceConfigurationError(f"{source_id}: invalid boolean key {_source_env_name(source_id, suffix)}")


def _parse_int(source_id: str, suffix: str, value: str, *, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DataSourceConfigurationError(f"{source_id}: invalid integer key {_source_env_name(source_id, suffix)}") from None
    if parsed < minimum:
        raise DataSourceConfigurationError(f"{source_id}: invalid integer key {_source_env_name(source_id, suffix)}")
    return parsed


def _optional_int(source_id: str, suffix: str, value: str | None, *, minimum: int) -> int | None:
    return None if value is None else _parse_int(source_id, suffix, value, minimum=minimum)


def _parse_float(source_id: str, suffix: str, value: str, *, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise DataSourceConfigurationError(f"{source_id}: invalid number key {_source_env_name(source_id, suffix)}") from None
    if parsed < minimum:
        raise DataSourceConfigurationError(f"{source_id}: invalid number key {_source_env_name(source_id, suffix)}")
    return parsed


def _optional_float(source_id: str, suffix: str, value: str | None, *, minimum: float) -> float | None:
    return None if value is None else _parse_float(source_id, suffix, value, minimum=minimum)


def _parse_enum(source_id: str, suffix: str, value: str, allowed: set[str]) -> str:
    normalized = value.strip().upper() if all(item == item.upper() for item in allowed) else value.strip().lower()
    if normalized not in allowed:
        raise DataSourceConfigurationError(f"{source_id}: invalid enum key {_source_env_name(source_id, suffix)}")
    return normalized


def _parse_csv(value: str | None, *, lower: bool = False) -> tuple[str, ...]:
    items = tuple(item.strip() for item in (value or "").split(",") if item.strip())
    if lower:
        return tuple(item.lower().strip(".") for item in items)
    return items


def _host_matches_allowed_hosts(hostname: str, allowed_hosts: tuple[str, ...]) -> bool:
    normalized_hostname = hostname.lower().strip(".")
    return any(
        normalized_hostname == allowed_host.lower().strip(".")
        or normalized_hostname.endswith(f".{allowed_host.lower().strip('.')}")
        for allowed_host in allowed_hosts
    )
