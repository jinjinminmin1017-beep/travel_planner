import os

from app.data_sources.config_loader import load_data_source_configs, load_project_env, runtime_statuses


PLANNED_REAL_SOURCE_IDS = {
    "amap_route",
    "baidu_map_route",
    "amadeus_flight_offers",
    "amadeus_flight_price",
    "variflight_status",
    "rail_authorized_partner",
    "ota_partner_redirect",
    "real_llm",
}
DEFAULT_ENABLED_REAL_SOURCE_IDS = {
    "osrm_route",
    "nominatim_geocode",
    "opensky_states",
    "irail_connections",
    "open_meteo_forecast",
    "amap_uri_redirect",
    "airline_official_redirect",
    "rail_12306_redirect",
}
OPTIONAL_DISABLED_REAL_SOURCE_IDS = {
    "baidu_uri_redirect",
}


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
        assert status.status == "DOWN"
        assert status.last_success_at is None
    for source_id in DEFAULT_ENABLED_REAL_SOURCE_IDS:
        status = statuses[source_id]
        assert status.enabled is True
        assert status.status == "OK"
        assert status.last_success_at is not None
    for source_id in OPTIONAL_DISABLED_REAL_SOURCE_IDS:
        status = statuses[source_id]
        assert status.enabled is False
        assert status.status == "DOWN"


def test_enabled_real_source_without_approval_or_key_is_degraded(monkeypatch):
    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_ENABLED", "true")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.enabled is True
    assert status.status == "DEGRADED"
    assert status.degraded is True
    assert status.degraded_reason == "required API credential environment variable is missing"

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.status == "DEGRADED"
    assert status.degraded_reason == "data source license is not approved"

    monkeypatch.setenv("TRAVEL_SOURCE_AMAP_ROUTE_LICENSE_STATUS", "APPROVED")
    status = {item.source_id: item for item in runtime_statuses("DEV")}["amap_route"]
    assert status.status == "OK"
    assert status.degraded is False


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
