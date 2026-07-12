import os

import pytest

from app.data_sources.config_loader import load_data_source_configs, load_project_env, runtime_statuses, validate_production_data_source_configs
from app.data_sources.llm_providers import OpenAICompatibleLLMProvider
from app.models.schemas import DataSourceConfig
from scripts.check_real_api_config import validate_env_example_sync, validate_public_tier


PLANNED_REAL_SOURCE_IDS = {
    "amap_route",
    "baidu_map_route",
    "airline_mu_public_query",
    "airline_cz_public_query",
    "airline_sc_public_query",
    "variflight_status",
    "real_llm",
}
DEFAULT_ENABLED_REAL_SOURCE_IDS = {
    "osrm_route",
    "nominatim_geocode",
    "opensky_states",
    "rail_12306_public_query",
    "open_meteo_forecast",
    "amap_uri_redirect",
    "airline_official_redirect",
    "rail_12306_redirect",
}
OPTIONAL_DISABLED_REAL_SOURCE_IDS = {
    "baidu_uri_redirect",
}


@pytest.fixture(autouse=True)
def clear_local_real_source_env(monkeypatch):
    monkeypatch.setattr("app.data_sources.config_loader._ENV_LOADED", True)
    for source_id in PLANNED_REAL_SOURCE_IDS | DEFAULT_ENABLED_REAL_SOURCE_IDS | OPTIONAL_DISABLED_REAL_SOURCE_IDS:
        prefix = f"TRAVEL_SOURCE_{source_id.upper()}"
        for suffix in ["ENABLED", "LICENSE_STATUS", "QPS_LIMIT", "COMMERCIAL_ALLOWED"]:
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    for key in [
        "TRAVEL_SOURCE_AMAP_ROUTE_ENABLED",
        "TRAVEL_SOURCE_AMAP_ROUTE_LICENSE_STATUS",
        "TRAVEL_SOURCE_AMAP_ROUTE_QPS_LIMIT",
        "AMAP_WEB_SERVICE_KEY",
        "AMAP_API_KEY",
        "TRAVEL_SOURCE_BAIDU_MAP_ROUTE_ENABLED",
        "TRAVEL_SOURCE_BAIDU_MAP_ROUTE_LICENSE_STATUS",
        "BAIDU_MAP_AK",
        "BAIDU_MAP_API_KEY",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_ENABLED",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_LICENSE_STATUS",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_QPS_LIMIT",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_MIN_INTERVAL_SECONDS",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_CACHE_TTL_SECONDS",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_BASE_URL",
        "TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_USER_AGENT",
        "TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_ENABLED",
        "TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_LICENSE_STATUS",
        "TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_BASE_URL",
        "TRAVEL_SOURCE_AIRLINE_CZ_PUBLIC_QUERY_ENABLED",
        "TRAVEL_SOURCE_AIRLINE_CZ_PUBLIC_QUERY_LICENSE_STATUS",
        "TRAVEL_SOURCE_AIRLINE_CZ_PUBLIC_QUERY_BASE_URL",
        "TRAVEL_SOURCE_AIRLINE_SC_PUBLIC_QUERY_ENABLED",
        "TRAVEL_SOURCE_AIRLINE_SC_PUBLIC_QUERY_LICENSE_STATUS",
        "TRAVEL_SOURCE_AIRLINE_SC_PUBLIC_QUERY_BASE_URL",
        "TRAVEL_SOURCE_REAL_LLM_ENABLED",
        "TRAVEL_SOURCE_REAL_LLM_LICENSE_STATUS",
        "TRAVEL_SOURCE_REAL_LLM_QPS_LIMIT",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "REAL_LLM_MAX_TOKENS",
        "REAL_LLM_THINKING_DISABLED",
        "VARIFLIGHT_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


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


def _llm_request_json() -> dict:
    client = _RecordingLLMClient()
    provider = OpenAICompatibleLLMProvider(api_key="test-key", model="test-model", client=client)
    provider._complete_json("system prompt", "user prompt")
    return client.requests[0]["json"]


def test_planned_real_sources_are_registered_but_disabled_in_dev_and_test():
    for environment in ("DEV", "TEST"):
        configs = {config.source_id: config for config in load_data_source_configs(environment)}
        assert PLANNED_REAL_SOURCE_IDS.issubset(configs)
        assert DEFAULT_ENABLED_REAL_SOURCE_IDS.issubset(configs)
        assert OPTIONAL_DISABLED_REAL_SOURCE_IDS.issubset(configs)

        for source_id in PLANNED_REAL_SOURCE_IDS:
            config = configs[source_id]
            assert config.enabled is False
            assert config.qps_limit == 0
            assert config.license_status == "PENDING_REVIEW"
            assert config.environment == environment
            assert not config.source_id.startswith("simulated_")
        for source_id in DEFAULT_ENABLED_REAL_SOURCE_IDS:
            config = configs[source_id]
            assert config.enabled is True
            assert config.qps_limit == 1
            assert config.license_status == "APPROVED"
            assert config.environment == environment
        for source_id in OPTIONAL_DISABLED_REAL_SOURCE_IDS:
            config = configs[source_id]
            assert config.enabled is False
            assert config.qps_limit == 0
            assert config.license_status == "PENDING_REVIEW"
            assert config.environment == environment


def test_disabled_real_sources_are_reported_as_down_runtime_statuses():
    statuses = {status.source_id: status for status in runtime_statuses("DEV")}

    for source_id in PLANNED_REAL_SOURCE_IDS:
        status = statuses[source_id]
        assert status.enabled is False
        assert status.health_status == "DISABLED"
        assert status.last_success_at is None
    for source_id in DEFAULT_ENABLED_REAL_SOURCE_IDS:
        status = statuses[source_id]
        assert status.enabled is True
        assert status.health_status == "OK"
        assert status.last_success_at is not None
    for source_id in OPTIONAL_DISABLED_REAL_SOURCE_IDS:
        status = statuses[source_id]
        assert status.enabled is False
        assert status.health_status == "DISABLED"


def test_enabled_real_source_without_approval_or_key_is_degraded(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", "true")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.enabled is True
    assert status.health_status == "DEGRADED"
    assert status.degraded_reason == "required API credential environment variable is missing"

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.health_status == "DEGRADED"
    assert status.degraded_reason == "data source license is not approved"

    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_LICENSE_STATUS", "APPROVED")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.health_status == "OK"
    assert status.degraded_reason is None


def test_llm_provider_disables_thinking_and_uses_default_max_tokens():
    request_json = _llm_request_json()

    assert request_json["thinking"] == {"type": "disabled"}
    assert request_json["max_tokens"] == 800
    assert request_json["response_format"] == {"type": "json_object"}
    assert "thinking" not in request_json["messages"][0]
    assert "thinking" not in request_json["messages"][1]


def test_llm_provider_max_tokens_can_be_overridden(monkeypatch):
    monkeypatch.setenv("REAL_LLM_MAX_TOKENS", "1200")

    request_json = _llm_request_json()

    assert request_json["max_tokens"] == 1200


@pytest.mark.parametrize("raw_value", ["bad", "0", "-5"])
def test_llm_provider_invalid_max_tokens_falls_back_to_default(monkeypatch, raw_value):
    monkeypatch.setenv("REAL_LLM_MAX_TOKENS", raw_value)

    request_json = _llm_request_json()

    assert request_json["max_tokens"] == 800


def test_llm_provider_can_omit_thinking_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("REAL_LLM_THINKING_DISABLED", "false")

    request_json = _llm_request_json()

    assert "thinking" not in request_json
    assert request_json["max_tokens"] == 800


def test_public_airline_source_rejects_non_allowlisted_base_url(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_ENABLED", "true")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_LICENSE_STATUS", "APPROVED")
    monkeypatch.setenv("TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_BASE_URL", "https://example.test")

    status = {item.source_id: item for item in runtime_statuses("DEV")}["airline_mu_public_query"]

    assert status.enabled is True
    assert status.health_status == "DEGRADED"
    assert status.degraded_reason == "official airline public query base URL is outside the source allowlist"


def test_project_env_loader_reads_local_env_file_without_overriding_existing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TRAVEL_SOURCE_AMAP_ROUTE_ENABLED=true",
                "AMAP_WEB_SERVICE_KEY=from-file",
                "EXISTING_VALUE=from-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", raising=False)
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-shell")

    load_project_env(env_file)

    assert load_data_source_configs("DEV")[1].enabled is True
    assert os.getenv("AMAP_WEB_SERVICE_KEY") == "from-file"
    assert os.getenv("EXISTING_VALUE") == "from-shell"


def test_prod_has_no_sources_until_explicit_approval():
    assert load_data_source_configs("PROD") == []


def test_env_example_is_synced_with_dev_data_source_config():
    assert validate_env_example_sync() == []


def test_ci_public_provider_config_tier_is_ready_without_secrets():
    assert validate_public_tier() == []


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

    with pytest.raises(ValueError, match="not production approved"):
        validate_production_data_source_configs([config])
