from __future__ import annotations

from datetime import timedelta
from typing import Protocol, cast
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from uuid import uuid4

from app.models.schemas import (
    BookingRedirect,
    BookingRedirectRequest,
    DataSourceMetadata,
    DataSourceType,
    FlightSegment,
    LocalTransferSegment,
    RailSegment,
    TimePoint,
    TravelPlan,
    now_timepoint,
)


class RedirectProviderError(RuntimeError):
    pass


class BookingRedirectProvider(Protocol):
    source_id: str

    def create_redirect(self, request: BookingRedirectRequest, plan: TravelPlan) -> BookingRedirect:
        ...


class Rail12306RedirectProvider:
    source_id = "rail_12306_redirect"

    def __init__(self, metadata: DataSourceMetadata) -> None:
        self.metadata = metadata

    def create_redirect(self, request: BookingRedirectRequest, plan: TravelPlan) -> BookingRedirect:
        segment = _target_segment(plan, request.segment_id)
        query = {}
        if isinstance(segment, RailSegment):
            query = {
                "from": segment.origin_station,
                "to": segment.destination_station,
                "train": segment.train_number,
                "date": segment.departure_time.datetime.date().isoformat(),
            }
        url = "https://www.12306.cn/index/"
        return _redirect(request.redirect_type, url, self.metadata, fallback_instruction=_manual_instruction("12306 官方网站", query))


class AirlineOfficialRedirectProvider:
    source_id = "airline_official_redirect"

    def __init__(self, metadata: DataSourceMetadata) -> None:
        self.metadata = metadata

    def create_redirect(self, request: BookingRedirectRequest, plan: TravelPlan) -> BookingRedirect:
        segment = _target_segment(plan, request.segment_id)
        airline_home = "https://www.travelsky.com/"
        query = {}
        if isinstance(segment, FlightSegment):
            carrier = segment.flight_number[:2].upper()
            airline_home = {
                "MU": "https://www.ceair.com/",
                "CZ": "https://www.csair.com/",
                "CA": "https://www.airchina.com.cn/",
                "HU": "https://www.hnair.com/",
                "SC": "https://www.sda.cn/",
            }.get(carrier, airline_home)
            query = {
                "from": segment.origin_airport,
                "to": segment.destination_airport,
                "flight": segment.flight_number,
                "date": segment.departure_time.datetime.date().isoformat(),
            }
        return _redirect(request.redirect_type, airline_home, self.metadata, fallback_instruction=_manual_instruction("航司官网", query))


class AmapUriRedirectProvider:
    source_id = "amap_uri_redirect"

    def __init__(self, metadata: DataSourceMetadata) -> None:
        self.metadata = metadata

    def create_redirect(self, request: BookingRedirectRequest, plan: TravelPlan) -> BookingRedirect:
        origin, destination, mode = _navigation_points(plan, request.segment_id)
        params = {
            "from": origin,
            "to": destination,
            "mode": "car" if mode in {"TAXI", "RIDE_HAILING"} else "bus",
            "src": "ai_travel_planner",
            "callnative": "0",
        }
        return _redirect(request.redirect_type, f"https://uri.amap.com/navigation?{urlencode(params)}", self.metadata)


class BaiduUriRedirectProvider:
    source_id = "baidu_uri_redirect"

    def __init__(self, metadata: DataSourceMetadata) -> None:
        self.metadata = metadata

    def create_redirect(self, request: BookingRedirectRequest, plan: TravelPlan) -> BookingRedirect:
        origin, destination, mode = _navigation_points(plan, request.segment_id)
        params = {
            "origin": origin,
            "destination": destination,
            "mode": "driving" if mode in {"TAXI", "RIDE_HAILING"} else "transit",
            "output": "html",
            "src": "ai_travel_planner",
        }
        return _redirect(request.redirect_type, f"https://api.map.baidu.com/direction?{urlencode(params)}", self.metadata)


def create_booking_redirect(request: BookingRedirectRequest, plan: TravelPlan, environment: str | None = None) -> BookingRedirect:
    provider = _select_provider(request.redirect_type, environment)
    if provider:
        try:
            return provider.create_redirect(request, plan)
        except RedirectProviderError:
            pass
    return _fallback_redirect(request.redirect_type)


def _select_provider(redirect_type: str, environment: str | None = None) -> BookingRedirectProvider | None:
    from app.data_sources.provider_registry import build_enabled_providers

    providers = {
        cast(BookingRedirectProvider, provider).source_id: cast(BookingRedirectProvider, provider)
        for provider in build_enabled_providers(
            {"rail_12306_redirect", "airline_official_redirect", "amap_uri_redirect", "baidu_uri_redirect"},
            environment,
        )
    }
    if redirect_type == "RAIL_12306" and "rail_12306_redirect" in providers:
        return providers["rail_12306_redirect"]
    if redirect_type == "AIRLINE" and "airline_official_redirect" in providers:
        return providers["airline_official_redirect"]
    if redirect_type in {"MAP_NAVIGATION", "RIDE_HAILING"}:
        if "amap_uri_redirect" in providers:
            return providers["amap_uri_redirect"]
        if "baidu_uri_redirect" in providers:
            return providers["baidu_uri_redirect"]
    return None


def _synthetic_metadata(source_id: str, source_name: str, source_type: DataSourceType) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=source_type,
        authority_level="A",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=False,
    )


def _redirect(redirect_type: str, url: str, metadata: DataSourceMetadata, fallback_instruction: str | None = None) -> BookingRedirect:
    _assert_redirect_only_url(url)
    generated_at = now_timepoint()
    return BookingRedirect(
        redirect_id=f"redir_{uuid4().hex[:8]}",
        redirect_type=redirect_type,  # type: ignore[arg-type]
        url_available=True,
        url=url,
        fallback_instruction=fallback_instruction,
        data_source=metadata,
        generated_at=generated_at,
        expires_at=_expires_at(generated_at),
    )


def _fallback_redirect(redirect_type: str) -> BookingRedirect:
    labels = {
        "RAIL_12306": "12306 官方网站或 App",
        "AIRLINE": "对应航司官网或 App",
        "MAP_NAVIGATION": "高德/百度地图",
        "RIDE_HAILING": "打车平台",
    }
    generated_at = now_timepoint()
    return BookingRedirect(
        redirect_id=f"redir_{uuid4().hex[:8]}",
        redirect_type=redirect_type,  # type: ignore[arg-type]
        url_available=False,
        url=None,
        fallback_instruction=f"请打开{labels.get(redirect_type, '对应平台')}手动搜索，本系统不代下单、不支付、不保存账号。",
        data_source=_synthetic_metadata("redirect_fallback", "Redirect Fallback Instruction", DataSourceType.INTERNAL_CALCULATION),
        generated_at=generated_at,
        expires_at=_expires_at(generated_at),
    )


def _target_segment(plan: TravelPlan, segment_id: str | None):
    if segment_id:
        segment = next((item for item in plan.segments if item.segment_id == segment_id), None)
        if segment is None:
            raise RedirectProviderError("segment_id does not exist in plan")
        return segment
    return plan.segments[0] if plan.segments else None


def _navigation_points(plan: TravelPlan, segment_id: str | None) -> tuple[str, str, str]:
    segment = _target_segment(plan, segment_id)
    if isinstance(segment, LocalTransferSegment):
        return segment.origin, segment.destination, segment.transfer_mode
    if isinstance(segment, RailSegment):
        return segment.origin_station, segment.destination_station, "RAIL"
    if isinstance(segment, FlightSegment):
        return segment.origin_airport, segment.destination_airport, "FLIGHT"
    raise RedirectProviderError("plan has no navigable segment")


def _manual_instruction(platform: str, query: dict[str, str]) -> str:
    if not query:
        return f"请打开{platform}手动搜索，本系统仅提供跳转，不代下单或支付。"
    query_text = "，".join(f"{key}={quote(str(value))}" for key, value in query.items())
    return f"请在{platform}手动核验并购票：{query_text}。本系统仅提供跳转，不代下单或支付。"


def _expires_at(generated_at: TimePoint) -> TimePoint:
    return TimePoint(
        datetime=generated_at.datetime + timedelta(minutes=15),
        timezone=generated_at.timezone,
        source_timezone=generated_at.source_timezone,
    )


def _assert_redirect_only_url(url: str) -> None:
    forbidden_fragments = {"login", "password", "cookie", "token", "pay", "payment", "order", "booking", "reserve", "passenger", "credential", "idcard"}
    parsed = urlparse(url)
    values = [parsed.path, parsed.fragment]
    values.extend(f"{key}={value}" for key, value in parse_qsl(parsed.query, keep_blank_values=True))
    lowered = " ".join(values).lower()
    if any(fragment in lowered for fragment in forbidden_fragments):
        raise RedirectProviderError("redirect URL contains transaction or credential parameters")
