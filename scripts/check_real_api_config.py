from __future__ import annotations

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

from app.data_sources.config_loader import load_data_source_configs, runtime_statuses  # noqa: E402

REQUIRED_FOR_FULL_LIVE_PLANNING = {
    "amadeus_flight_offers": "航班搜索与报价",
    "rail_authorized_partner": "铁路时刻、票价和余票",
}
MAP_PROVIDER_SOURCE_IDS = ("amap_route", "baidu_map_route", "osrm_route")
OPTIONAL_PUBLIC_READ_ONLY_SOURCE_IDS = {
    "nominatim_geocode": "地点解析辅助",
    "opensky_states": "航班动态辅助",
    "open_meteo_forecast": "天气风险辅助",
    "irail_connections": "铁路公开时刻辅助",
}


def main() -> int:
    configs = {item.source_id: item for item in load_data_source_configs()}
    statuses = {item.source_id: item for item in runtime_statuses()}
    failures: list[str] = []

    ready_map = next(
        (
            source_id
            for source_id in MAP_PROVIDER_SOURCE_IDS
            if configs.get(source_id) and statuses.get(source_id) and configs[source_id].enabled and statuses[source_id].status == "OK"
        ),
        None,
    )
    if ready_map is None:
        failures.append("map_route: 没有任何地图路线 Provider 处于 OK 状态，无法用于本地接驳路线与费用")

    for source_id, purpose in REQUIRED_FOR_FULL_LIVE_PLANNING.items():
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
        if status.status != "OK":
            reason = status.degraded_reason or status.status
            failures.append(f"{source_id}: 状态不是 OK（{reason}），无法用于{purpose}")
            continue
        if source_id == "amadeus_flight_offers":
            base_url = (os.getenv("AMADEUS_BASE_URL") or "https://test.api.amadeus.com").rstrip("/")
            if base_url != "https://api.amadeus.com":
                failures.append(
                    "amadeus_flight_offers: AMADEUS_BASE_URL 仍指向测试环境，"
                    "生产报价必须使用 https://api.amadeus.com"
                )

    if failures:
        print("真实 API 完整规划配置未就绪：")
        for failure in failures:
            print(f"- {failure}")
        print()
        print("已就绪的公开只读/官方入口 Provider：")
        if ready_map:
            print(f"- {ready_map}: OK，用于本地接驳路线与费用估算")
        for source_id, purpose in OPTIONAL_PUBLIC_READ_ONLY_SOURCE_IDS.items():
            status = statuses.get(source_id)
            if status and status.enabled and status.status == "OK":
                print(f"- {source_id}: OK，用于{purpose}")
        print()
        print("请按 .env.example 配置航班报价和铁路票价/余票的真实授权 key，并设置对应 TRAVEL_SOURCE_*_ENABLED / LICENSE_STATUS。")
        return 1

    print("真实 API 完整规划基础配置已就绪：")
    print(f"- {ready_map}: OK，用于本地接驳路线与费用估算")
    for source_id, purpose in OPTIONAL_PUBLIC_READ_ONLY_SOURCE_IDS.items():
        status = statuses.get(source_id)
        if status and status.enabled and status.status == "OK":
            print(f"- {source_id}: OK，用于{purpose}")
    for source_id, purpose in REQUIRED_FOR_FULL_LIVE_PLANNING.items():
        print(f"- {source_id}: OK，用于{purpose}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
