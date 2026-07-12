from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

from app.data_sources.config_loader import load_project_env, runtime_statuses  # noqa: E402
from app.data_sources.flight_providers import (  # noqa: E402
    FlightSearchRequest,
    FlightStateRequest,
    get_flight_states_with_enabled_provider,
    search_flight_offers_with_enabled_provider_result,
)
from app.data_sources.geocoding_providers import GeocodeRequest, geocode_with_enabled_provider_result  # noqa: E402
from app.data_sources.map_providers import MapRouteRequest, estimate_route_with_enabled_provider  # noqa: E402
from app.data_sources.rail_providers import (  # noqa: E402
    RailSearchRequest,
    search_rail_offers_with_enabled_provider_result,
)
from app.data_sources.redirect_providers import create_booking_redirect  # noqa: E402
from app.data_sources.weather_providers import WeatherForecastRequest, get_weather_forecast_with_enabled_provider_result  # noqa: E402
from app.models.schemas import (  # noqa: E402
    BookingRedirectRequest,
    FlightSegment,
    GeoPoint,
    LocalTransferSegment,
    RailSegment,
    TimePoint,
    TransportMode,
)

RELEVANT_SOURCE_IDS = [
    "amap_route",
    "baidu_map_route",
    "osrm_route",
    "nominatim_geocode",
    "airline_mu_public_query",
    "airline_cz_public_query",
    "airline_sc_public_query",
    "opensky_states",
    "open_meteo_forecast",
    "rail_12306_public_query",
    "rail_12306_redirect",
    "airline_official_redirect",
    "amap_uri_redirect",
]
PUBLIC_SMOKE_PROVIDERS = ["map", "geocode", "flight-status", "weather", "redirect"]
SECRET_SMOKE_PROVIDERS = ["flight"]


def _env(name: str, default: str) -> str:
    import os

    return os.getenv(name) or default


def _date_env(name: str, default_days: int = 30) -> date:
    value = _env(name, "")
    if value:
        return date.fromisoformat(value)
    return date.today() + timedelta(days=default_days)


def _enabled_ok(source_id: str) -> bool:
    status = next((item for item in runtime_statuses() if item.source_id == source_id), None)
    return bool(status and status.enabled and status.health_status == "OK")


def print_status_summary() -> None:
    import os

    env_path = ROOT / ".env"
    print(f"环境文件: {env_path} ({'存在' if env_path.exists() else '不存在'})")
    print(f"APP_ENV: {os.getenv('APP_ENV') or 'DEV'}")
    statuses = {item.source_id: item for item in runtime_statuses()}
    for source_id in RELEVANT_SOURCE_IDS:
        status = statuses.get(source_id)
        if status is None:
            print(f"- {source_id}: 未登记")
            continue
        reason = f", reason={status.degraded_reason}" if status.degraded_reason else ""
        print(f"- {source_id}: enabled={status.enabled}, status={status.health_status}{reason}")
    print()


def smoke_map() -> bool:
    print("地图 Provider live smoke:")
    if not (_enabled_ok("amap_route") or _enabled_ok("baidu_map_route") or _enabled_ok("osrm_route")):
        print("- SKIP/FAIL: amap_route / baidu_map_route / osrm_route 均未处于 OK 状态")
        return False
    estimate = estimate_route_with_enabled_provider(
        MapRouteRequest(
            origin=GeoPoint(name="上海嘉定南翔格林公馆", latitude=31.295500, longitude=121.323200),
            destination=GeoPoint(name="上海虹桥站", latitude=31.200000, longitude=121.326900),
            mode=TransportMode.TAXI,
            origin_city="上海",
            destination_city="上海",
        )
    )
    if estimate is None:
        print("- FAIL: 已启用地图 Provider，但未返回可用路线")
        return False
    cost = estimate.estimated_cost.display_text if estimate.estimated_cost else "无费用字段"
    print(f"- OK: {estimate.data_source.source_id}, {estimate.distance_meters}m, {estimate.duration_minutes}分钟, {cost}")
    return True


def smoke_geocode() -> bool:
    print("地点解析 Provider live smoke:")
    if not _enabled_ok("nominatim_geocode"):
        print("- SKIP/FAIL: nominatim_geocode 未处于 OK 状态")
        return False
    request = GeocodeRequest(
        query=_env("LIVE_SMOKE_GEOCODE_QUERY", "青岛栈桥"),
        country_codes=_env("LIVE_SMOKE_GEOCODE_COUNTRY_CODES", "cn"),
        limit=int(_env("LIVE_SMOKE_GEOCODE_LIMIT", "1")),
    )
    result = geocode_with_enabled_provider_result(request)
    if not result.candidates:
        print(f"- FAIL: 未返回地点解析结果。attempted={result.attempted_source_ids}, reason={result.failure_message}")
        return False
    first = result.candidates[0]
    print(f"- OK: {first.data_source.source_id}, {first.display_name}, lat={first.point.latitude}, lon={first.point.longitude}")
    return True


def smoke_flight() -> bool:
    print("航班官方公开采集 Provider live smoke:")
    ready_sources = [source_id for source_id in ("airline_mu_public_query", "airline_cz_public_query", "airline_sc_public_query") if _enabled_ok(source_id)]
    if not ready_sources:
        print("- SKIP/FAIL: 没有 airline_*_public_query 处于 OK 状态")
        return False
    request = FlightSearchRequest(
        origin_iata=_env("LIVE_SMOKE_FLIGHT_ORIGIN", "SHA"),
        destination_iata=_env("LIVE_SMOKE_FLIGHT_DESTINATION", "TAO"),
        departure_date=_date_env("LIVE_SMOKE_DEPARTURE_DATE"),
        adults=int(_env("LIVE_SMOKE_ADULTS", "1")),
        currency_code=_env("LIVE_SMOKE_CURRENCY", "CNY"),
        max_results=int(_env("LIVE_SMOKE_FLIGHT_MAX_RESULTS", "3")),
        non_stop=True,
    )
    result = search_flight_offers_with_enabled_provider_result(request)
    if not result.offers:
        print(f"- FAIL: 未返回航班 offer。attempted={result.attempted_source_ids}, reason={result.failure_message}")
        return False
    first = result.offers[0]
    if not first.cabin_options:
        print(f"- FAIL: 航班 offer 没有可售舱位。source={first.data_source.source_id}, offer_id={first.offer_id}")
        return False
    first_segment = first.segments[0] if first.segments else None
    route = f"{first_segment.origin_iata}->{first_segment.destination_iata}" if first_segment else "unknown route"
    flight_no = f"{first_segment.carrier_code}{first_segment.flight_number}" if first_segment else "unknown flight"
    cabins = ",".join(f"{item.cabin_type}:{item.availability}" for item in first.cabin_options)
    print(f"- OK: {first.data_source.source_id}, {route}, {flight_no}, {first.total_price.display_text}, cabins={cabins}, evidence={first.evidence_id}")
    return True


def smoke_flight_status() -> bool:
    print("航班动态 Provider live smoke:")
    if not _enabled_ok("opensky_states"):
        print("- SKIP/FAIL: opensky_states 未处于 OK 状态")
        return False
    request = FlightStateRequest(
        lamin=float(_env("LIVE_SMOKE_OPENSKY_LAMIN", "45")),
        lomin=float(_env("LIVE_SMOKE_OPENSKY_LOMIN", "5")),
        lamax=float(_env("LIVE_SMOKE_OPENSKY_LAMAX", "55")),
        lomax=float(_env("LIVE_SMOKE_OPENSKY_LOMAX", "15")),
    )
    states = get_flight_states_with_enabled_provider(request)
    if not states:
        print("- FAIL: opensky_states 已启用，但未返回 aircraft states。可尝试调整 LIVE_SMOKE_OPENSKY_* bbox。")
        return False
    first = states[0]
    print(f"- OK: {first.data_source.source_id}, count={len(states)}, first={first.callsign or first.icao24}, country={first.origin_country}")
    return True


def smoke_weather() -> bool:
    print("天气 Provider live smoke:")
    if not _enabled_ok("open_meteo_forecast"):
        print("- SKIP/FAIL: open_meteo_forecast 未处于 OK 状态")
        return False
    request = WeatherForecastRequest(
        latitude=float(_env("LIVE_SMOKE_WEATHER_LATITUDE", "36.0662")),
        longitude=float(_env("LIVE_SMOKE_WEATHER_LONGITUDE", "120.3826")),
        timezone=_env("LIVE_SMOKE_WEATHER_TIMEZONE", "Asia/Shanghai"),
    )
    result = get_weather_forecast_with_enabled_provider_result(request)
    if not result.forecasts:
        print(f"- FAIL: 未返回天气数据。attempted={result.attempted_source_ids}, reason={result.failure_message}")
        return False
    forecast = result.forecasts[0]
    print(
        "- OK: "
        f"{forecast.data_source.source_id}, temp={forecast.temperature_celsius}°C, "
        f"wind={forecast.wind_speed_kmh}km/h, precipitation={forecast.precipitation_mm}mm"
    )
    return True


def smoke_rail() -> bool:
    print("12306 公开查询铁路 Provider live smoke:")
    if not _enabled_ok("rail_12306_public_query"):
        print("- SKIP/FAIL: rail_12306_public_query 未处于 OK 状态")
        return False
    request = RailSearchRequest(
        train_number=_env("LIVE_SMOKE_RAIL_TRAIN_NUMBER", ""),
        origin_station=_env("LIVE_SMOKE_RAIL_ORIGIN_STATION", "上海虹桥"),
        destination_station=_env("LIVE_SMOKE_RAIL_DESTINATION_STATION", "北京南"),
        departure_date=_date_env("LIVE_SMOKE_RAIL_DEPARTURE_DATE"),
    )
    result = search_rail_offers_with_enabled_provider_result(request)
    if not result.offers:
        print(f"- FAIL: 未返回铁路 offer。attempted={result.attempted_source_ids}, reason={result.failure_message}")
        return False
    first = result.offers[0]
    seat = first.seat_options[0]
    print(f"- OK: {first.data_source.source_id}, {first.train_number}, {first.origin_station}->{first.destination_station}, {seat.seat_type} {seat.price.display_text}")
    return True


def smoke_redirect() -> bool:
    print("Redirect-only live smoke:")
    plan = _sample_redirect_plan()
    checks = [
        ("RAIL_12306", "seg_rail", "rail_12306_redirect"),
        ("AIRLINE", "seg_flight", "airline_official_redirect"),
        ("MAP_NAVIGATION", "seg_transfer", "amap_uri_redirect"),
    ]
    ok = True
    for redirect_type, segment_id, expected_source in checks:
        request = BookingRedirectRequest(
            request_id="req_live_smoke_redirect",
            idempotency_key=f"idem_{redirect_type.lower()}",
            plan_id=plan.plan_id,
            segment_id=segment_id,
            redirect_type=redirect_type,
        )
        redirect = create_booking_redirect(request, plan)
        if not redirect.url_available or redirect.data_source.source_id != expected_source or not redirect.url:
            print(f"- FAIL: {redirect_type} 未生成授权跳转，source={redirect.data_source.source_id}, instruction={redirect.fallback_instruction}")
            ok = False
            continue
        status = _probe_redirect_url(redirect.url)
        print(f"- OK: {redirect_type}, source={redirect.data_source.source_id}, url={redirect.url}, http={status}")
    return ok


def _sample_redirect_plan():
    tp = TimePoint(datetime=_date_env("LIVE_SMOKE_DEPARTURE_DATE").isoformat() + "T09:00:00+08:00", timezone="Asia/Shanghai")
    rail_segment = RailSegment.model_construct(
        segment_id="seg_rail",
        segment_type="RAIL",
        train_number=_env("LIVE_SMOKE_RAIL_TRAIN_NUMBER", "G234"),
        origin_station=_env("LIVE_SMOKE_RAIL_ORIGIN_STATION", "上海虹桥"),
        destination_station=_env("LIVE_SMOKE_RAIL_DESTINATION_STATION", "青岛北"),
        departure_time=tp,
        arrival_time=tp,
        duration_minutes=350,
    )
    flight_segment = FlightSegment.model_construct(
        segment_id="seg_flight",
        segment_type="FLIGHT",
        flight_number=_env("LIVE_SMOKE_AIRLINE_FLIGHT_NUMBER", "MU5511"),
        origin_airport="上海虹桥机场",
        destination_airport="青岛胶东机场",
        departure_time=tp,
        arrival_time=tp,
        duration_minutes=100,
    )
    transfer_segment = LocalTransferSegment.model_construct(
        segment_id="seg_transfer",
        segment_type="LOCAL_TRANSFER",
        origin="上海嘉定南翔格林公馆",
        destination="上海虹桥站",
        transfer_mode=TransportMode.TAXI,
    )
    return SimpleNamespace(
        plan_id="plan_live_smoke_redirect",
        plan_type="DIRECT_RAIL",
        segments=[rail_segment, flight_segment, transfer_segment],
    )


def _probe_redirect_url(url: str) -> str:
    try:
        response = httpx.get(url, timeout=8.0, follow_redirects=False)
        return str(response.status_code)
    except httpx.HTTPError as exc:
        return f"probe_error:{exc.__class__.__name__}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live smoke checks against configured real travel APIs.")
    parser.add_argument(
        "--tier",
        choices=("public", "secret", "full"),
        default="public",
        help="public runs no-key read-only/redirect checks; secret runs explicitly approved source checks; full runs all checks.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=("map", "geocode", "flight", "flight-status", "weather", "rail", "redirect"),
        help="Provider to check. Repeatable. Defaults to all. Rail is opt-in for low-frequency 12306 public query smoke.",
    )
    parser.add_argument("--status", action="store_true", help="Print provider status summary before smoke checks.")
    args = parser.parse_args()
    load_project_env()
    if args.status:
        print_status_summary()
    if args.provider:
        selected = args.provider
    elif args.tier == "public":
        selected = PUBLIC_SMOKE_PROVIDERS
    elif args.tier == "secret":
        selected = SECRET_SMOKE_PROVIDERS
    else:
        selected = [*PUBLIC_SMOKE_PROVIDERS, *SECRET_SMOKE_PROVIDERS]
    checks = {
        "map": smoke_map,
        "geocode": smoke_geocode,
        "flight": smoke_flight,
        "flight-status": smoke_flight_status,
        "weather": smoke_weather,
        "rail": smoke_rail,
        "redirect": smoke_redirect,
    }
    results = [checks[name]() for name in selected]
    if all(results):
        print("真实 API live smoke 全部通过。")
        return 0
    print("真实 API live smoke 未全部通过。请检查 .env 授权、启用开关、日期和路线参数。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
