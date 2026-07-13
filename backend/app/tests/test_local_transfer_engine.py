from dataclasses import dataclass, field

from app.data_sources.map_providers import MapRouteEstimate, MapRouteProviderResult, data_source_metadata
from app.models.schemas import PlanType, SourceFailure, TransportMode, money
import pytest

from app.services.local_transfer_engine import LocalTransferUnavailable, build_local_transfer_segment


@dataclass
class _IssueSink:
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    def add_missing(self, component: str) -> None:
        if component not in self.missing:
            self.missing.append(component)

    def add_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)

    def add_source_failure(self, **kwargs) -> None:
        self.failures.append(kwargs)


def _estimate_for_mode(request, environment=None):
    distance_by_mode = {
        TransportMode.TAXI: 1200,
        TransportMode.SUBWAY: 1300,
        TransportMode.BUS: 1450,
        TransportMode.WALK: 900,
    }
    duration_by_mode = {
        TransportMode.TAXI: 6,
        TransportMode.SUBWAY: 12,
        TransportMode.BUS: 16,
        TransportMode.WALK: 11,
    }
    return MapRouteProviderResult(
        estimate=MapRouteEstimate(
            distance_meters=distance_by_mode[request.mode],
            duration_minutes=duration_by_mode[request.mode],
            estimated_cost=money(0 if request.mode == TransportMode.WALK else 1200, estimated=True),
            summary=f"real {request.mode.value.lower()} route",
            data_source=data_source_metadata("amap_route", "AMap Route Planning API"),
        ),
        attempted_source_ids=["amap_route"],
    )


def test_local_transfer_engine_exposes_walk_for_short_non_airport_routes():
    segment = build_local_transfer_segment(
        segment_id="seg_short_walk",
        origin="上海虹桥站",
        destination="上海站",
        default_minutes=15,
        default_cost_minor=3200,
        route_estimator=_estimate_for_mode,
    )

    option_ids = {option.option_id for option in segment.transfer_options}
    walk = next(option for option in segment.transfer_options if option.option_id == "transfer_walk")
    assert {"transfer_taxi", "transfer_subway", "transfer_bus", "transfer_walk"}.issubset(option_ids)
    assert walk.transfer_mode == "WALK"
    assert walk.estimated_cost.amount_minor == 0
    assert walk.walking_distance_meters == 900
    assert "real walk route" in walk.ride_instruction


def test_local_transfer_engine_hides_walk_for_airport_routes():
    segment = build_local_transfer_segment(
        segment_id="seg_airport",
        origin="上海嘉定南翔格林公馆",
        destination="上海虹桥机场",
        default_minutes=32,
        default_cost_minor=7800,
        route_estimator=_estimate_for_mode,
    )

    assert "transfer_walk" not in {option.option_id for option in segment.transfer_options}


def test_local_transfer_engine_blocks_segment_when_all_map_routes_are_empty():
    sink = _IssueSink()

    def empty_estimate(request, environment=None):
        return MapRouteProviderResult(estimate=None, attempted_source_ids=["amap_route"], failure_message="empty route result")

    with pytest.raises(LocalTransferUnavailable):
        build_local_transfer_segment(
            segment_id="seg_fallback",
            origin="上海嘉定南翔格林公馆",
            destination="上海虹桥站",
            default_minutes=38,
            default_cost_minor=7800,
            route_estimator=empty_estimate,
            issue_sink=sink,
        )

    assert "map_route" in sink.missing
    assert sink.failures
    assert all(not failure["fallback_used"] for failure in sink.failures)
    assert any(failure["error_code"] == "MAP_TRANSFER_UNAVAILABLE" for failure in sink.failures)
    assert any("无法形成完整门到门方案" in warning for warning in sink.warnings)


def test_unselected_transfer_failure_does_not_mark_selected_route_partial():
    sink = _IssueSink()

    def mixed_estimate(request, environment=None):
        if request.mode == TransportMode.TAXI:
            return _estimate_for_mode(request, environment)
        return MapRouteProviderResult(
            estimate=None,
            attempted_source_ids=["amap_route"],
            failure_message=f"empty {request.mode.value} route",
            error_code="MAP_ROUTE_EMPTY",
            query_status="UNAVAILABLE",
        )

    segment = build_local_transfer_segment(
        segment_id="seg_selected_verified",
        origin="上海嘉定南翔格林公馆",
        destination="上海虹桥站",
        default_minutes=38,
        default_cost_minor=7800,
        selected_option_id="transfer_taxi",
        route_estimator=mixed_estimate,
        issue_sink=sink,
    )

    assert segment.route_status == "PRIMARY_VERIFIED"
    assert sink.missing == []
    assert sink.warnings == []
    assert sink.failures
