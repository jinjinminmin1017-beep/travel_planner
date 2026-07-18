import os
from pathlib import Path

import pytest

from app.data_sources.config_loader import (
    DataSourceConfigurationError,
    load_data_source_configs,
    load_data_source_settings,
    load_project_env,
    reset_data_source_settings_cache,
    runtime_statuses,
    validate_production_data_source_configs,
)
from app.data_sources.llm_providers import OpenAICompatibleLLMProvider
from app.data_sources.provider_registry import ADAPTER_REGISTRY, validate_enabled_provider_factories
from app.models.schemas import DataSourceConfig
from scripts.check_real_api_config import validate_env_example_sync, validate_public_tier

PLANNED_REAL_SOURCE_IDS = {
    "amap_route",
    "baidu_map_route",
    "real_llm",
}
DEFAULT_ENABLED_REAL_SOURCE_IDS = {
    "osrm_route",
    "nominatim_geocode",
    "opensky_states",
    "rail_12306_public_query",
    "airline_9c_public_query",
    "airline_hu_public_query",
    "airline_qw_public_query",
    "open_meteo_forecast",
    "amap_uri_redirect",
    "airline_official_redirect",
    "rail_12306_redirect",
}


class _FakeLLMResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"schema_version":"1.17"}'}}]}


class _RecordingLLMClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return _FakeLLMResponse()


def _llm_request_json(*, max_tokens: int = 800, thinking_disabled: bool = True) -> dict:
    client = _RecordingLLMClient()
    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="test-model",
        client=client,
        max_tokens=max_tokens,
        thinking_disabled=thinking_disabled,
    )
    provider._complete_json("system prompt", "user prompt")
    return client.requests[0]["json"]


def _reload() -> None:
    reset_data_source_settings_cache()


def test_env_only_defaults_register_expected_sources_for_dev_and_test():
    for environment in ("DEV", "TEST"):
        configs = {config.source_id: config for config in load_data_source_configs(environment)}
        assert PLANNED_REAL_SOURCE_IDS.issubset(configs)
        assert DEFAULT_ENABLED_REAL_SOURCE_IDS.issubset(configs)
        assert all(config.environment == environment for config in configs.values())
        assert all(not configs[source_id].enabled for source_id in PLANNED_REAL_SOURCE_IDS)
        assert all(configs[source_id].enabled for source_id in DEFAULT_ENABLED_REAL_SOURCE_IDS)


def test_disabled_sources_are_reported_without_requiring_credentials():
    statuses = {status.source_id: status for status in runtime_statuses("DEV")}

    for source_id in PLANNED_REAL_SOURCE_IDS:
        assert statuses[source_id].health_status == "DISABLED"
        assert statuses[source_id].last_success_at is None


def test_enabled_source_missing_required_key_fails_startup(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_QPS_LIMIT", "1")
    monkeypatch.delenv("TRAVEL_SOURCE_AMAP_ROUTE_API_KEY", raising=False)
    _reload()

    with pytest.raises(DataSourceConfigurationError, match="TRAVEL_SOURCE_AMAP_ROUTE_API_KEY"):
        load_data_source_settings()


def test_enabled_pending_license_is_degraded_after_valid_configuration(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_QPS_LIMIT", "1")
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_API_KEY", "test-key")
    _reload()

    status = {item.source_id: item for item in runtime_statuses()}["amap_route"]

    assert status.enabled is True
    assert status.health_status == "DEGRADED"
    assert status.degraded_reason == "data source license is not approved"


def test_unknown_source_key_fails_without_echoing_value(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_UNKNOWN_PROVIDER_API_KEY", "super-secret")
    _reload()

    with pytest.raises(DataSourceConfigurationError) as error:
        load_data_source_settings()

    assert "TRAVEL_SOURCE_UNKNOWN_PROVIDER_API_KEY" in str(error.value)
    assert "super-secret" not in str(error.value)


@pytest.mark.parametrize(
    "key",
    [
        "TRAVEL_SOURCE_INTERNAL_CALC_QPS_LIMIT",
        "TRAVEL_SOURCE_OSRM_ROUTE_CACHE_TTL_SECONDS",
    ],
)
def test_behaviorally_ineffective_adapter_keys_are_rejected(monkeypatch, key):
    monkeypatch.setenv(key, "1")
    _reload()

    with pytest.raises(DataSourceConfigurationError, match="unsupported keys"):
        load_data_source_settings()


def test_duplicate_source_id_and_unknown_adapter_fail(monkeypatch):
    registered = os.environ["TRAVEL_DATA_SOURCE_IDS"]
    monkeypatch.setenv("TRAVEL_DATA_SOURCE_IDS", f"{registered},internal_calc")
    _reload()
    with pytest.raises(DataSourceConfigurationError, match="duplicate"):
        load_data_source_settings()

    monkeypatch.setenv("TRAVEL_DATA_SOURCE_IDS", registered)
    monkeypatch.setenv("TRAVEL_SOURCE_INTERNAL_CALC_ADAPTER", "not_registered")
    _reload()
    with pytest.raises(DataSourceConfigurationError, match="unknown adapter"):
        load_data_source_settings()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TRAVEL_SOURCE_INTERNAL_CALC_ENABLED", "maybe"),
        ("TRAVEL_SOURCE_INTERNAL_CALC_QPS_LIMIT", "many"),
        ("TRAVEL_SOURCE_INTERNAL_CALC_LICENSE_STATUS", "UNKNOWN"),
        ("TRAVEL_SOURCE_OSRM_ROUTE_BASE_URL", "https://example.test"),
    ],
)
def test_invalid_source_values_fail_closed(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    _reload()

    with pytest.raises(DataSourceConfigurationError):
        load_data_source_settings()


def test_settings_snapshot_is_immutable_until_explicit_reload(monkeypatch):
    first = load_data_source_settings()
    monkeypatch.setenv("TRAVEL_SOURCE_OSRM_ROUTE_ENABLED", "false")

    assert load_data_source_settings() is first
    assert first.get("osrm_route").enabled is True

    _reload()
    assert load_data_source_settings().get("osrm_route").enabled is False


def test_llm_provider_uses_constructor_injected_runtime_settings():
    request_json = _llm_request_json(max_tokens=1200, thinking_disabled=False)

    assert request_json["max_tokens"] == 1200
    assert "thinking" not in request_json
    assert request_json["response_format"] == {"type": "json_object"}


def test_llm_provider_default_disables_thinking():
    request_json = _llm_request_json()

    assert request_json["thinking"] == {"type": "disabled"}
    assert request_json["max_tokens"] == 800


def test_project_env_loader_does_not_override_existing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_VALUE=from-file\nEXISTING_VALUE=from-file\n", encoding="utf-8")
    monkeypatch.delenv("NEW_VALUE", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-shell")

    load_project_env(env_file)

    assert os.getenv("NEW_VALUE") == "from-file"
    assert os.getenv("EXISTING_VALUE") == "from-shell"


def test_env_example_and_adapter_registry_are_consistent():
    assert validate_env_example_sync() == []
    assert set(ADAPTER_REGISTRY) == {source.adapter for source in load_data_source_settings().sources}


def test_env_example_contains_only_behaviorally_effective_provider_keys():
    env_example = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")
    cache_ttl_keys = [
        line.split("=", 1)[0]
        for line in env_example.splitlines()
        if line.startswith("TRAVEL_SOURCE_") and "_CACHE_TTL_SECONDS=" in line
    ]

    assert "_HTTP_METHOD=" not in env_example
    assert "AIRLINE_MU_PUBLIC_QUERY" not in env_example
    assert "VARIFLIGHT_STATUS" not in env_example
    assert cache_ttl_keys == [
        "TRAVEL_SOURCE_AIRLINE_9C_PUBLIC_QUERY_CACHE_TTL_SECONDS",
        "TRAVEL_SOURCE_AIRLINE_HU_PUBLIC_QUERY_CACHE_TTL_SECONDS",
        "TRAVEL_SOURCE_AIRLINE_QW_PUBLIC_QUERY_CACHE_TTL_SECONDS",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_CACHE_TTL_SECONDS",
    ]


def test_public_provider_config_and_factories_are_ready_without_secrets():
    assert validate_public_tier() == []
    validate_enabled_provider_factories()


def test_production_rejects_enabled_unapproved_data_source():
    config = DataSourceConfig(
        source_id="amap_route",
        source_name="AMap Route Planning API",
        source_type="MAP",
        authority_level="A",
        environment="PROD",
        license_status="PENDING_REVIEW",
        commercial_allowed=False,
        enabled=True,
        qps_limit=1,
        sla_level="PENDING_REVIEW",
        fallback_source_id=None,
        last_checked_at=None,
    )

    with pytest.raises(DataSourceConfigurationError, match="LICENSE_STATUS"):
        validate_production_data_source_configs([config])
