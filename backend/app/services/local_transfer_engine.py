from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.data_sources.map_providers import MapRouteEstimate, MapRouteProviderResult, MapRouteRequest
from app.models.schemas import (
    LocalTransferOption,
    LocalTransferSegment,
    GeoPoint,
    PlanType,
    RiskLevel,
    SourceFailureClass,
    SourceFailureHandlingStrategy,
    TransportMode,
    money,
)
from app.services.location_resolver import LocationPointResolution, resolve_location_city, resolve_location_point


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


class LocalTransferUnavailable(RuntimeError):
    def __init__(self, origin: str, destination: str, error_code: str) -> None:
        super().__init__(f"verified local transfer unavailable: {origin} -> {destination} ({error_code})")
        self.origin = origin
        self.destination = destination
        self.error_code = error_code


RouteEstimator = Callable[[MapRouteRequest, str | None], MapRouteProviderResult]


@dataclass(frozen=True)
class TransferContext:
    origin: str
    destination: str
    route_estimator: RouteEstimator
    issue_sink: LocalTransferIssueSink | None = None

    @property
    def is_airport_transfer(self) -> bool:
        return "机场" in self.origin or "机场" in self.destination


@dataclass(frozen=True)
class RouteResolution:
    estimate: MapRouteEstimate | None
    route_status: str
    error_code: str | None = None


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
    # The legacy defaults remain in the call shape for compatibility, but are
    # intentionally not used: new responses may contain only provider facts.
    del default_minutes, default_cost_minor
    context = TransferContext(origin, destination, route_estimator, issue_sink)
    options = build_local_transfer_options(context)
    if not options:
        error_code = "MAP_TRANSFER_UNAVAILABLE"
        _record_transfer_unavailable(context, error_code)
        raise LocalTransferUnavailable(origin, destination, error_code)

    selected = next((option for option in options if option.option_id == selected_option_id), options[0])
    return LocalTransferSegment(
        segment_id=segment_id,
        origin=origin,
        destination=destination,
        transfer_mode=selected.transfer_mode,
        distance_meters=selected.distance_meters,
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
    origin = _coerce_location_resolution(resolve_location_point(context.origin), context.origin)
    destination = _coerce_location_resolution(resolve_location_point(context.destination), context.destination)
    if not origin.point or not destination.point:
        _record_location_failure(context, origin, destination)
        return []

    options: list[LocalTransferOption] = []
    for mode in (TransportMode.TAXI, TransportMode.SUBWAY, TransportMode.BUS, TransportMode.WALK):
        resolution = _estimate_route(context, origin, destination, mode)
        option = _option_from_resolution(context, mode, resolution)
        if option:
            options.append(option)
    return options


def _coerce_location_resolution(value: LocationPointResolution | GeoPoint, query: str) -> LocationPointResolution:
    if isinstance(value, LocationPointResolution):
        return value
    return LocationPointResolution(
        query=query,
        city_context=resolve_location_city(query),
        status="RESOLVED",
        point=value,
        source_id="test_or_legacy_resolver",
        candidates=[],
        attempted_source_ids=["test_or_legacy_resolver"],
    )


def _estimate_route(
    context: TransferContext,
    origin: LocationPointResolution,
    destination: LocationPointResolution,
    mode: TransportMode,
) -> RouteResolution:
    assert origin.point is not None and destination.point is not None
    result = context.route_estimator(
        MapRouteRequest(
            origin=origin.point,
            destination=destination.point,
            mode=mode,
            origin_city=origin.city_context,
            destination_city=destination.city_context,
        ),
        None,
    )
    if result.estimate is None:
        source_id = result.attempted_source_ids[-1] if result.attempted_source_ids else "map_route"
        error_code = result.error_code or "MAP_ROUTE_UNAVAILABLE"
        _record_route_failure(
            context,
            source_id=source_id,
            error_code=error_code,
            message=result.failure_message or f"map route unavailable for {context.origin} -> {context.destination}",
        )
        return RouteResolution(None, "UNAVAILABLE", error_code)
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


def _option_from_resolution(
    context: TransferContext,
    mode: TransportMode,
    resolution: RouteResolution,
) -> LocalTransferOption | None:
    estimate = resolution.estimate
    if estimate is None:
        return None
    if estimate.distance_meters <= 0 or estimate.duration_minutes <= 0:
        _record_route_failure(
            context,
            source_id=estimate.data_source.source_id,
            error_code="MAP_ROUTE_FACTS_INVALID",
            message=f"invalid route facts for {context.origin} -> {context.destination}",
        )
        return None
    if context.is_airport_transfer and mode == TransportMode.WALK:
        return None
    if mode == TransportMode.WALK and estimate.distance_meters > 2200:
        return None

    estimated_cost = estimate.estimated_cost
    if mode == TransportMode.WALK:
        estimated_cost = estimated_cost or money(0)
    if estimated_cost is None:
        _record_route_failure(
            context,
            source_id=estimate.data_source.source_id,
            error_code="MAP_ROUTE_COST_MISSING",
            message=f"route cost missing for {context.origin} -> {context.destination}",
        )
        return None

    option_id, label = {
        TransportMode.TAXI: ("transfer_taxi", "打车"),
        TransportMode.SUBWAY: ("transfer_subway", "地铁"),
        TransportMode.BUS: ("transfer_bus", "公交"),
        TransportMode.WALK: ("transfer_walk", "步行"),
    }[mode]
    walking_distance = estimate.distance_meters if mode == TransportMode.WALK else estimate.walking_distance_meters
    return LocalTransferOption(
        option_id=option_id,
        transfer_mode=mode,
        label=label,
        estimated_cost=estimated_cost,
        duration_minutes=estimate.duration_minutes,
        distance_meters=estimate.distance_meters,
        access_station=None,
        egress_station=None,
        access_instruction=f"从 {context.origin} 出发。",
        ride_instruction=f"按{estimate.summary}前往 {context.destination}。",
        egress_instruction=f"到达 {context.destination} 后请现场确认入口位置。",
        walking_distance_meters=walking_distance,
        data_source=estimate.data_source,
        route_status=resolution.route_status,
        route_error_code=resolution.error_code,
    )


def _record_location_failure(
    context: TransferContext,
    origin: LocationPointResolution,
    destination: LocationPointResolution,
) -> None:
    failed = origin if not origin.point else destination
    error_code = failed.error_code or "MAP_COORDINATES_MISSING"
    source_id = failed.attempted_source_ids[-1] if failed.attempted_source_ids else "map_geocoding"
    attempted = ",".join(failed.attempted_source_ids) or "none"
    message = (
        f"location resolution failed for {failed.query}; status={failed.status}; "
        f"attempted_sources={attempted}; detail={failed.failure_message or 'no verified coordinates'}"
    )
    user_message = _location_failure_message(error_code)
    if context.issue_sink:
        context.issue_sink.add_missing("map_route")
        context.issue_sink.add_warning(user_message)
        context.issue_sink.add_source_failure(
            source_id=source_id,
            adapter_name="LocationResolver",
            failure_class=SourceFailureClass.CORE_FACT_FAILURE,
            handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
            error_code=error_code,
            message=message,
            user_visible_message=user_message,
            impacted_plan_types=_impacted_plan_types(),
            source_used_id=None,
            fallback_source_id=None,
            fallback_reason=None,
            fallback_used=False,
        )


def _record_route_failure(context: TransferContext, source_id: str, error_code: str, message: str) -> None:
    if not context.issue_sink:
        return
    context.issue_sink.add_source_failure(
        source_id=source_id,
        adapter_name="LocalTransferEngine",
        failure_class=SourceFailureClass.AUXILIARY_DATA_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.PARTIAL_RESULT,
        error_code=error_code,
        message=message,
        user_visible_message=_route_failure_message(error_code),
        impacted_plan_types=_impacted_plan_types(),
        source_used_id=None,
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
    )


def _record_transfer_unavailable(context: TransferContext, error_code: str) -> None:
    if not context.issue_sink:
        return
    message = f"no verified local-transfer option for {context.origin} -> {context.destination}"
    user_message = "该接驳段没有任何已验证路线，无法形成完整门到门方案。"
    context.issue_sink.add_missing("map_route")
    context.issue_sink.add_warning(user_message)
    context.issue_sink.add_source_failure(
        source_id="map_route",
        adapter_name="LocalTransferEngine",
        failure_class=SourceFailureClass.CORE_FACT_FAILURE,
        handling_strategy=SourceFailureHandlingStrategy.BLOCK_PLAN,
        error_code=error_code,
        message=message,
        user_visible_message=user_message,
        impacted_plan_types=_impacted_plan_types(),
        source_used_id=None,
        fallback_source_id=None,
        fallback_reason=None,
        fallback_used=False,
    )


def _location_failure_message(error_code: str) -> str:
    if error_code == "MAP_LOCATION_AMBIGUOUS":
        return "地点存在多个同名候选，请补充城市、区县或完整地址后重试。"
    if error_code == "MAP_GEOCODING_TIMEOUT":
        return "地点搜索超时，当前无法验证接驳路线，请稍后重试。"
    if error_code == "MAP_GEOCODING_RATE_LIMITED":
        return "地点搜索请求暂时受限，当前无法验证接驳路线，请稍后重试。"
    return "地点搜索未获得完整坐标，当前无法形成完整门到门路线。"


def _route_failure_message(error_code: str) -> str:
    return {
        "MAP_ROUTE_TIMEOUT": "该接驳路线查询超时，未生成估算数字。",
        "MAP_ROUTE_RATE_LIMITED": "该接驳路线查询触发限流，未生成估算数字。",
        "MAP_ROUTE_EMPTY": "该接驳方式未返回可用路线，已从可选方式中移除。",
        "MAP_ROUTE_NOT_ENABLED": "该接驳方式暂无已启用的地图数据源。",
        "MAP_MODE_UNSUPPORTED": "当前地图数据源不支持该接驳方式。",
        "MAP_ROUTE_COST_MISSING": "该接驳方式未返回可验证费用，已从可选方式中移除。",
    }.get(error_code, "该接驳方式暂未取得可验证的地图结果。")


def _traffic_risk(option: LocalTransferOption) -> RiskLevel:
    if option.transfer_mode == TransportMode.WALK:
        return RiskLevel.LOW if (option.walking_distance_meters or 0) <= 1200 else RiskLevel.MEDIUM
    if option.transfer_mode == TransportMode.BUS:
        return RiskLevel.MEDIUM
    if option.duration_minutes > 55:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _impacted_plan_types() -> list[PlanType]:
    return [
        PlanType.DIRECT_RAIL,
        PlanType.TRANSFER_RAIL,
        PlanType.DIRECT_FLIGHT,
        PlanType.TRANSFER_FLIGHT,
        PlanType.FLIGHT_RAIL_MIXED,
    ]
