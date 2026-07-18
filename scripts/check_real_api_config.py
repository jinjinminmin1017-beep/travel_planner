from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.data_sources.config_loader import (  # noqa: E402
    DataSourceConfigurationError,
    expected_source_env_suffixes,
    load_data_source_configs,
    load_data_source_settings,
    required_secret_envs,
    runtime_statuses,
)
from app.data_sources.provider_registry import ADAPTER_REGISTRY  # noqa: E402

MAP_PROVIDER_SOURCE_IDS = ("amap_route", "baidu_map_route", "osrm_route")
PUBLIC_READ_ONLY_SOURCE_IDS = {
    "osrm_route": "本地接驳路线",
    "nominatim_geocode": "地点解析辅助",
    "opensky_states": "航班动态辅助",
    "open_meteo_forecast": "天气风险辅助",
    "rail_12306_public_query": "12306 公开匿名车次、票价和席别查询",
    "rail_12306_redirect": "12306 官方入口跳转",
    "airline_official_redirect": "航司官网跳转",
    "airline_9c_public_query": "春秋航空公开匿名航班、票价和舱位查询",
    "airline_hu_public_query": "海航公开匿名航班、票价和舱位查询",
    "airline_qw_public_query": "青岛航空公开匿名航班、票价和舱位查询",
    "amap_uri_redirect": "地图导航跳转",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_env_example_sync() -> list[str]:
    values = _parse_env_file(ROOT / ".env.example")
    failures: list[str] = []
    try:
        snapshot = load_data_source_settings(environ=values)
    except DataSourceConfigurationError as exc:
        return [f".env.example 配置无效：{exc}"]

    configured_adapters = {source.adapter for source in snapshot.sources}
    missing_factories = sorted(configured_adapters - set(ADAPTER_REGISTRY))
    unused_factories = sorted(set(ADAPTER_REGISTRY) - configured_adapters)
    if missing_factories:
        failures.append(f".env.example adapter 缺少工厂：{', '.join(missing_factories)}")
    if unused_factories:
        failures.append(f"adapter 注册表存在未使用项：{', '.join(unused_factories)}")
    for source in snapshot.sources:
        for suffix in sorted(expected_source_env_suffixes(source.adapter)):
            key = f"TRAVEL_SOURCE_{source.source_id.upper()}_{suffix}"
            if key not in values:
                failures.append(f".env.example 缺少 {key}")
    return failures


def _configs_and_statuses():
    return (
        {item.source_id: item for item in load_data_source_configs()},
        {item.source_id: item for item in runtime_statuses()},
    )


def validate_public_tier() -> list[str]:
    configs, statuses = _configs_and_statuses()
    failures = validate_env_example_sync()
    ready_map = next(
        (
            source_id
            for source_id in MAP_PROVIDER_SOURCE_IDS
            if configs.get(source_id)
            and statuses.get(source_id)
            and configs[source_id].enabled
            and statuses[source_id].health_status == "OK"
        ),
        None,
    )
    if ready_map is None:
        failures.append("public tier: 没有公开地图路线 Provider 处于 OK 状态")

    for source_id, purpose in PUBLIC_READ_ONLY_SOURCE_IDS.items():
        config = configs.get(source_id)
        status = statuses.get(source_id)
        if config is None or status is None:
            failures.append(f"public tier: {source_id} 未登记，无法用于{purpose}")
            continue
        if required_secret_envs(source_id):
            failures.append(f"public tier: {source_id} 需要密钥，不得进入默认公开档")
        if not config.enabled:
            failures.append(f"public tier: {source_id} 未启用，无法用于{purpose}")
        if config.license_status != "APPROVED":
            failures.append(f"public tier: {source_id} 许可未批准")
        if config.commercial_allowed:
            failures.append(f"public tier: {source_id} 默认公开档不得允许商业使用")
        if config.qps_limit > 1:
            failures.append(f"public tier: {source_id} 默认公开档必须低频")
        if status.health_status != "OK":
            failures.append(f"public tier: {source_id} 状态不是 OK（{status.degraded_reason or status.health_status}）")
    return failures


def validate_secret_tier(selected_sources: list[str]) -> list[str]:
    if "flight" in selected_sources:
        return ["flight: 已实现的春秋、海航和青岛航空查询无需密钥，请使用 public tier 验证"]
    return []


def validate_full_tier() -> list[str]:
    return validate_public_tier()


def _print_failures(title: str, failures: list[str]) -> None:
    print(title)
    for failure in failures:
        print(f"- {failure}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ENV-only real API provider configuration.")
    parser.add_argument("--tier", choices=("public", "secret", "full"), default="public")
    parser.add_argument("--source", action="append", choices=("flight",))
    args = parser.parse_args()

    try:
        if args.tier == "public":
            failures = validate_public_tier()
        elif args.tier == "secret":
            failures = validate_secret_tier(args.source or ["flight"])
        else:
            failures = validate_full_tier()
    except DataSourceConfigurationError as exc:
        failures = [str(exc)]

    if failures:
        _print_failures(f"真实 API {args.tier} 配置未就绪：", failures)
        return 1
    print(f"真实 API {args.tier} 配置已就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
