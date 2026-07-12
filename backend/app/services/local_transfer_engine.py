from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.data_sources.map_providers import MapRouteEstimate, MapRouteProviderResult, MapRouteRequest
from app.models.schemas import (
    DataSourceMetadata,
    DataSourceType,
    LocalTransferOption,
    LocalTransferSegment,
    PlanType,
    RiskLevel,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    TransportMode,
    money,
    now_timepoint,
)
from app.services.location_resolver import nearby_transit_stop, resolve_location_city, resolve_location_point


class LocalTransferIssueSink(Protocol):
    def add_missing(self, component: str) -> None:
        ...

    def add_warning(self, warning: str) -> None:
        ...

    def add_source_failure(
        self,
        *,
        source_id: str,
        adapter_name: str,
        failure_class: SourceFailureClass,
        handling_strategy: SourceFailureHandlingStrategy,
        message: str,
        user_visible_message: str,
        impacted_plan_types: list[PlanType],
        error_code: str,
        source_used_id: str | None,
        fallback_source_id: str | None,
        fallback_reason: str | None,
        fallback_used: bool,
    ) -> None:
        ...


RouteEstimator = Callable[[MapRouteRequest, str | None], MapRouteProviderResult]


@dataclass(frozen=True)
class TransferContext:
    origin: str
    destination: str
    default_minutes: int
    default_cost_minor: int
    route_estimator: RouteEstimator
    issue_sink: LocalTransferIssueSink | None = None

    @property
    def rule_distance_meters(self) -> int:
        return max(300, self.default_minutes * 650)

    @property
    def is_airport_transfer(self) -> bool:
        return "机场" in self.origin or "机场" in self.destination

    @property
    def is_station_transfer(self) -> bool:
        return self.origin.endswith("站") or self.destination.endswith("站") or "站" in self.origin or "站" in self.destination


@dataclass(frozen=True)
class RouteResolution:
    estimate: MapRouteEstimate | None
    route_status: str
    error_code: str | None = None


INTERNAL_TRANSFER_SOURCE = DataSourceMetadata(
    source_id="internal_calc",
    source_name="Internal Local Transfer Engine",
    source_type=DataSourceType.INTERNAL_CALCULATION,
    authority_level="B",
    license_status="APPROVED",
    commercial_allowed=False,
    fetched_at=now_timepoint(),
    cacheable=True,
)


def build_local_transfer_segment(
    *,
    segment_id: str,
    origin: str,
    destination: str,
    default_minutes: int,
    default_cost_minor: int,
    selected_option_id: str = "transfer_taxi",
    route_estimator: RouteEstimator,
    issue_sink: LocalTransferIssueSink | None = None,
) -> LocalTransferSegment:
    context = TransferContext(origin, destination, default_minutes, default_cost_minor, route_estimator, issue_sink)
    options = build_local_transfer_options(context)
    selected = next((option for option in options if option.option_id == selected_option_id), options[0])
    if selected.route_status in {"RULE_ESTIMATED", "UNAVAILABLE"}:
        _record_selected_degradation(context, selected)
    return LocalTransferSegment(
        segment_id=segment_id,
        origin=origin,
        destination=destination,
        transfer_mode=selected.transfer_mode,
        distance_meters=_distance_for_selected(context, selected),
        duration_minutes=selected.duration_minutes,
        estimated_cost=selected.estimated_cost,
        traffic_risk=_traffic_risk(selected),
        walking_distance_meters=selected.walking_distance_meters,
        option_id=selected.option_id,
        available_options=[option.option_id for option in options],
        transfer_options=options,
        data_source=selected.data_source,
        route_status=selected.route_status,
        route_error_code=selected.route_error_code,
        redirect_info=None,
    )


def build_local_transfer_options(context: TransferContext) -> list[LocalTransferOption]:
    taxi = _estimate_or_fallback(context, TransportMode.TAXI)
    subway = _estimate_or_fallback(context, TransportMode.SUBWAY)
    bus = _estimate_or_fallback(context, TransportMode.BUS)
    walk = _estimate_or_fallback(context, TransportMode.WALK)

    options = [
        _taxi_option(context, taxi),
        _transit_option(context, TransportMode.SUBWAY, subway),
        _transit_option(context, TransportMode.BUS, bus),
    ]
    walk_option = _walk_option(context, walk)
    if walk_option:
        options.append(walk_option)
    return options


def _estimate_or_fallback(context: TransferContext, mode: TransportMode) -> RouteResolution:
    origin_point = resolve_location_point(context.origin)
    destination_point = resolve_location_point(context.destination)
    if not origin_point or not destination_point:
        _record_route_detail(
            context,
            source_id="map_route",
            error_code="MAP_COORDINATES_MISSING",
            message=f"missing coordinates for local transfer: {context.origin} -> {context.destination}",
            user_message="该接驳路线坐标不完整，已使用规则估算。",
        )
        return RouteResolution(None, "RULE_ESTIMATED", "MAP_COORDINATES_MISSING")

    result = context.route_estimator(
        MapRouteRequest(
            origin=origin_point,
            destination=destination_point,
            mode=mode,
            origin_city=resolve_location_city(context.origin),
            destination_city=resolve_location_city(context.destination),
        ),
        None,
    )
    if result.estimate is None:
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "map_route"
        error_code = result.error_code or "MAP_ROUTE_UNAVAILABLE"
        _record_route_detail(
            context,
            source_id=source_id,
            error_code=error_code,
            message=result.failure_message or f"map route unavailable for {mode.value}: {context.origin} -> {context.destination}",
            user_message=_route_failure_message(error_code),
        )
        return RouteResolution(None, "RULE_ESTIMATED", error_code)
    if result.fallback_used and context.issue_sink:
        context.issue_sink.add_source_failure(
            source_id=result.attempted_source_ids[0],
            adapter_name="MapRouteProvider",
            failure_class=SourceFailureClass.FALLBACK_AVAILABLE_FAILURE,
            handling_strategy=SourceFailureHandlingStrategy.FALLBACK,
            error_code="MAP_ROUTE_FALLBACK_USED",
            message=result.fallback_reason or "map route fallback provider used",
            user_visible_message="当前路线已由备用地图数据源提供，可正常使用。",
            impacted_plan_types=_impacted_plan_types(),
            source_used_id=result.fallback_source_id,
            fallback_source_id=result.fallback_source_id,
            fallback_reason=result.fallback_reason,
            fallback_used=True,
        )
    return RouteResolution(result.estimate, result.query_status)


def _taxi_option(context: TransferContext, resolution: RouteResolution) -> LocalTransferOption:
    estimate = resolution.estimate
    duration = estimate.duration_minutes if estimate else context.default_minutes
    cost = estimate.estimated_cost if estimate and estimate.estimated_cost else money(context.default_cost_minor, estimated=True)
    return LocalTransferOption(
        option_id="transfer_taxi",
        transfer_mode=TransportMode.TAXI,
        label="打车",
        estimated_cost=cost,
        duration_minutes=duration,
        distance_meters=estimate.distance_meters if estimate else None,
        access_instruction=f"从 {context.origin} 上车，确认目的地为 {context.destination}。",
        ride_instruction=f"按 {estimate.summary} 估算行驶。" if estimate else "地图 Provider 暂不可用，本段按规则估算行驶时间和费用。",
        egress_instruction=f"在 {context.destination} 下车，跳转后以地图或打车平台确认为准。",
        walking_distance_meters=120,
        data_source=estimate.data_source if estimate else INTERNAL_TRANSFER_SOURCE,
        route_status=resolution.route_status,
        route_error_code=resolution.error_code,
    )


def _transit_option(context: TransferContext, mode: TransportMode, resolution: RouteResolution) -> LocalTransferOption:
    estimate = resolution.estimate
    is_subway = mode == TransportMode.SUBWAY
    label = "地铁" if is_subway else "公交"
    option_id = "transfer_subway" if is_subway else "transfer_bus"
    access = nearby_transit_stop(context.origin, mode, "origin")
    egress = nearby_transit_stop(context.destination, mode, "destination")
    fallback_minutes = context.default_minutes + (18 if is_subway else 28)
    fallback_cost = money(900 if is_subway else 500, estimated=True)
    walking_distance = 780 if is_subway else 980
    if context.is_airport_transfer and is_subway:
        walking_distance += 260
    if context.is_station_transfer and not is_subway:
        walking_distance += 180
    return LocalTransferOption(
        option_id=option_id,
        transfer_mode=mode,
        label=label,
        estimated_cost=estimate.estimated_cost if estimate and estimate.estimated_cost else fallback_cost,
        duration_minutes=estimate.duration_minutes if estimate else fallback_minutes,
        distance_meters=estimate.distance_meters if estimate else None,
        access_station=access,
        egress_station=egress,
        access_instruction=f"从 {context.origin} 步行/短驳至 {access}。",
        ride_instruction=f"按 {estimate.summary} 前往 {egress}。" if estimate else f"地图 Provider 暂不可用，本段按规则估算乘坐{label}至 {egress}。",
        egress_instruction=f"从 {egress} 步行/短驳至 {context.destination}。",
        walking_distance_meters=walking_distance,
        data_source=estimate.data_source if estimate else INTERNAL_TRANSFER_SOURCE,
        route_status=resolution.route_status,
        route_error_code=resolution.error_code,
    )


def _walk_option(context: TransferContext, resolution: RouteResolution) -> LocalTransferOption | None:
    estimate = resolution.estimate
    distance = estimate.distance_meters if estimate else context.rule_distance_meters
    if context.is_airport_transfer or distance > 2200:
        return None
    duration = estimate.duration_minutes if estimate else max(6, int(distance / 75))
    return LocalTransferOption(
        option_id="transfer_walk",
        transfer_mode=TransportMode.WALK,
        label="步行",
        estimated_cost=money(0, estimated=True),
        duration_minutes=duration,
        distance_meters=distance,
        access_instruction=f"从 {context.origin} 出发，按步行路线前往目的地。",
        ride_instruction=f"按 {estimate.summary} 步行。" if estimate else "地图 Provider 暂不可用，本段按规则估算步行时间。",
        egress_instruction=f"到达 {context.destination}，请现场确认入口位置。",
        walking_distance_meters=distance,
        data_source=estimate.data_source if estimate else INTERNAL_TRANSFER_SOURCE,
        route_status=resolution.route_status,
        route_error_code=resolution.error_code,
    )


def _record_route_detail(context: TransferContext, source_id: str, error_code: str, message: str, user_message: str) -> None:
    if not context.issue_sink:
        return
    context.issue_sink.add_source_failure(
        source_id=source_id,
        adapter_name="LocalTransferEngine",
        failure_class=SourceFailureClass.FALLBACK_AVAILABLE_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.FALLBACK,
        error_code=error_code,
        message=message,
        user_visible_message=user_message,
        impacted_plan_types=_impacted_plan_types(),
        source_used_id=INTERNAL_TRANSFER_SOURCE.source_id,
        fallback_source_id=INTERNAL_TRANSFER_SOURCE.source_id,
        fallback_reason=message,
        fallback_used=True,
    )


def _record_selected_degradation(context: TransferContext, selected: LocalTransferOption) -> None:
    if not context.issue_sink:
        return
    message = _route_failure_message(selected.route_error_code or "MAP_ROUTE_UNAVAILABLE")
    context.issue_sink.add_missing("map_route")
    context.issue_sink.add_warning(message)


def _route_failure_message(error_code: str) -> str:
    return {
        "MAP_COORDINATES_MISSING": "该接驳路线坐标不完整，已使用规则估算。",
        "MAP_ROUTE_TIMEOUT": "该接驳路线查询超时，已使用规则估算。",
        "MAP_ROUTE_RATE_LIMITED": "该接驳路线查询触发限流，已使用规则估算。",
        "MAP_ROUTE_EMPTY": "该接驳路线未返回可用结果，已使用规则估算。",
        "MAP_ROUTE_NOT_ENABLED": "该接驳方式暂无已启用的地图数据源，已使用规则估算。",
        "MAP_MODE_UNSUPPORTED": "当前地图数据源不支持该接驳方式，已使用规则估算。",
    }.get(error_code, "该接驳路线暂未取得地图结果，已使用规则估算。")


def _traffic_risk(option: LocalTransferOption) -> RiskLevel:
    if option.transfer_mode == TransportMode.WALK:
        return RiskLevel.LOW if option.walking_distance_meters <= 1200 else RiskLevel.MEDIUM
    if option.transfer_mode == TransportMode.BUS:
        return RiskLevel.MEDIUM
    if option.duration_minutes > 55:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _distance_for_selected(context: TransferContext, selected: LocalTransferOption) -> int:
    if selected.distance_meters is not None:
        return selected.distance_meters
    if selected.transfer_mode == TransportMode.WALK:
        return selected.walking_distance_meters
    return max(context.rule_distance_meters, selected.duration_minutes * 550)


def _impacted_plan_types() -> list[PlanType]:
    return [PlanType.DIRECT_RAIL, PlanType.TRANSFER_RAIL, PlanType.DIRECT_FLIGHT, PlanType.TRANSFER_FLIGHT, PlanType.FLIGHT_RAIL_MIXED]
