from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.data_sources.config_loader import load_data_source_configs, required_secret_envs, runtime_statuses  # noqa: E402
from app.data_sources.flight_provider_contracts import AIRLINE_PUBLIC_QUERY_CONTRACTS, airline_public_query_contract  # noqa: E402
from app.models.schemas import DataSourceConfig  # noqa: E402

REQUIRED_FOR_FULL_LIVE_PLANNING = {
    source_id: f"{contract.source_name}（{','.join(contract.carrier_codes)}）"
    for source_id, contract in AIRLINE_PUBLIC_QUERY_CONTRACTS.items()
}
SECRET_TIER_SOURCES = {
    "flight": tuple(AIRLINE_PUBLIC_QUERY_CONTRACTS),
}
MAP_PROVIDER_SOURCE_IDS = ("amap_route", "baidu_map_route", "osrm_route")
PUBLIC_READ_ONLY_SOURCE_IDS = {
    "osrm_route": "本地接驳路线与费用估算",
    "nominatim_geocode": "地点解析辅助",
    "opensky_states": "航班动态辅助",
    "open_meteo_forecast": "天气风险辅助",
    "rail_12306_public_query": "12306 公开匿名车次、票价和有票席别查询",
    "rail_12306_redirect": "12306 官方入口跳转",
    "airline_official_redirect": "航司官网跳转",
    "amap_uri_redirect": "地图导航跳转",
}


def _env_key(source_id: str, suffix: str) -> str:
    return f"TRAVEL_SOURCE_{source_id.upper()}_{suffix}"


def _parse_env_example() -> dict[str, str]:
    path = ROOT / ".env.example"
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_env_example_sync() -> list[str]:
    values = _parse_env_example()
    failures: list[str] = []
    dev_config_path = BACKEND / "app" / "data_sources" / "data_sources.dev.json"
    committed_configs = [DataSourceConfig.model_validate(item) for item in json.loads(dev_config_path.read_text(encoding="utf-8"))]
    for config in committed_configs:
        expected = {_env_key(config.source_id, "LICENSE_STATUS"): config.license_status, _env_key(config.source_id, "COMMERCIAL_ALLOWED"): str(config.commercial_allowed).lower()}
        if config.source_id not in AIRLINE_PUBLIC_QUERY_CONTRACTS:
            expected.update({_env_key(config.source_id, "ENABLED"): str(config.enabled).lower(), _env_key(config.source_id, "QPS_LIMIT"): str(config.qps_limit)})
        for key, expected_value in expected.items():
            actual = values.get(key)
            if actual is None:
                failures.append(f".env.example 缺少 {key}")
            elif actual.lower() != expected_value.lower():
                failures.append(f".env.example {key}={actual}，应为 {expected_value}")
        if config.source_id in AIRLINE_PUBLIC_QUERY_CONTRACTS:
            for suffix in ("ENABLED", "QPS_LIMIT"):
                key = _env_key(config.source_id, suffix)
                if key in values:
                    failures.append(f".env.example 不应设置 {key}；航司默认由 LICENSE_STATUS 单变量启用")
    return failures


def _configs_and_statuses():
    return {item.source_id: item for item in load_data_source_configs()}, {item.source_id: item for item in runtime_statuses()}


def validate_public_tier() -> list[str]:
    configs, statuses = _configs_and_statuses()
    failures = validate_env_example_sync()

    ready_map = next(
        (
            source_id
            for source_id in MAP_PROVIDER_SOURCE_IDS
            if configs.get(source_id) and statuses.get(source_id) and configs[source_id].enabled and statuses[source_id].health_status == "OK"
        ),
        None,
    )
    if ready_map is None:
        failures.append("public tier: 没有任何无密钥/公开地图路线 Provider 处于 OK 状态")

    for source_id, purpose in PUBLIC_READ_ONLY_SOURCE_IDS.items():
        config = configs.get(source_id)
        status = statuses.get(source_id)
        if config is None or status is None:
            failures.append(f"public tier: {source_id} 未登记，无法用于{purpose}")
            continue
        if required_secret_envs(source_id):
            failures.append(f"public tier: {source_id} 需要密钥，不得进入默认 CI 公开档")
        if not config.enabled:
            failures.append(f"public tier: {source_id} 未启用，无法用于{purpose}")
        if config.license_status != "APPROVED":
            failures.append(f"public tier: {source_id} license_status={config.license_status}，无法用于{purpose}")
        if config.commercial_allowed:
            failures.append(f"public tier: {source_id} commercial_allowed=true，默认 CI 公开档必须只读/非商业")
        if config.qps_limit > 1:
            failures.append(f"public tier: {source_id} qps_limit={config.qps_limit}，默认 CI 公开档必须低频")
        if status.health_status != "OK":
            reason = status.degraded_reason or status.health_status
            failures.append(f"public tier: {source_id} 状态不是 OK（{reason}），无法用于{purpose}")
    return failures


def validate_secret_tier(selected_sources: list[str]) -> list[str]:
    configs, statuses = _configs_and_statuses()
    failures: list[str] = []
    for group in selected_sources:
        for source_id in SECRET_TIER_SOURCES[group]:
            purpose = REQUIRED_FOR_FULL_LIVE_PLANNING[source_id]
            config = configs.get(source_id)
            status = statuses.get(source_id)
            if config is None or status is None:
                failures.append(f"{source_id}: 未登记，无法用于{purpose}")
                continue
            if not config.enabled:
                failures.append(f"{source_id}: 未启用，无法用于{purpose}")
                continue
            if config.license_status != "APPROVED":
                failures.append(f"{source_id}: license_status={config.license_status}，无法用于{purpose}")
                continue
            if status.health_status != "OK":
                reason = status.degraded_reason or status.health_status
                failures.append(f"{source_id}: 状态不是 OK（{reason}），无法用于{purpose}")
                continue
            if source_id in SECRET_TIER_SOURCES["flight"]:
                contract = airline_public_query_contract(source_id)
                if contract is None or contract.blocking_reason:
                    reason = contract.blocking_reason if contract else "missing contract"
                    failures.append(f"{source_id}: source-specific executable contract is not ready ({reason})")
                base_url = (os.getenv(_env_key(source_id, "BASE_URL")) or "").rstrip("/")
                if not base_url:
                    failures.append(f"{source_id}: 缺少 {_env_key(source_id, 'BASE_URL')}，无法执行官方公开前端采集")
                if config.fallback_source_id is not None:
                    failures.append(f"{source_id}: fallback_source_id 必须为空，航班核心事实缺失时应阻断方案")
    return failures


def validate_full_tier() -> list[str]:
    configs, statuses = _configs_and_statuses()
    failures = validate_public_tier()

    ready_map = next(
        (
            source_id
            for source_id in MAP_PROVIDER_SOURCE_IDS
            if configs.get(source_id) and statuses.get(source_id) and configs[source_id].enabled and statuses[source_id].health_status == "OK"
        ),
        None,
    )
    if ready_map is None:
        failures.append("map_route: 没有任何地图路线 Provider 处于 OK 状态，无法用于本地接驳路线与费用")

    failures.extend(validate_secret_tier(["flight"]))
    return failures


def _print_failures(title: str, failures: list[str]) -> None:
    print(title)
    for failure in failures:
        print(f"- {failure}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check real API provider configuration at CI-safe tiers.")
    parser.add_argument("--tier", choices=("public", "secret", "full"), default="public", help="public is no-key CI-safe; secret checks explicitly approved non-default providers; full requires all production providers.")
    parser.add_argument("--source", action="append", choices=tuple(SECRET_TIER_SOURCES), help="Non-default provider group to check. Repeatable. Defaults to flight for --tier secret.")
    args = parser.parse_args()

    if args.tier == "public":
        failures = validate_public_tier()
    elif args.tier == "secret":
        failures = validate_secret_tier(args.source or list(SECRET_TIER_SOURCES))
    else:
        failures = validate_full_tier()

    if failures:
        _print_failures(f"真实 API {args.tier} 配置未就绪：", failures)
        print()
        print("已就绪的公开只读/官方入口 Provider：")
        configs, statuses = _configs_and_statuses()
        ready_map = next(
            (
                source_id
                for source_id in MAP_PROVIDER_SOURCE_IDS
                if configs.get(source_id) and statuses.get(source_id) and configs[source_id].enabled and statuses[source_id].health_status == "OK"
            ),
            None,
        )
        if ready_map:
            print(f"- {ready_map}: OK，用于本地接驳路线与费用估算")
        for source_id, purpose in PUBLIC_READ_ONLY_SOURCE_IDS.items():
            status = statuses.get(source_id)
            if status and status.enabled and status.health_status == "OK":
                print(f"- {source_id}: OK，用于{purpose}")
        print()
        print("请按 .env.example 配置对应档位的授权 key，并设置 TRAVEL_SOURCE_*_ENABLED / LICENSE_STATUS / QPS_LIMIT / COMMERCIAL_ALLOWED。")
        return 1

    print(f"真实 API {args.tier} 配置已就绪。")
    if args.tier in {"public", "full"}:
        _, statuses = _configs_and_statuses()
        for source_id, purpose in PUBLIC_READ_ONLY_SOURCE_IDS.items():
            status = statuses.get(source_id)
            if status and status.enabled and status.health_status == "OK":
                print(f"- {source_id}: OK，用于{purpose}")
    if args.tier in {"secret", "full"}:
        _, statuses = _configs_and_statuses()
        selected = args.source or list(SECRET_TIER_SOURCES)
        for group in selected:
            for source_id in SECRET_TIER_SOURCES[group]:
                purpose = REQUIRED_FOR_FULL_LIVE_PLANNING[source_id]
                print(f"- {source_id}: OK，用于{purpose}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
