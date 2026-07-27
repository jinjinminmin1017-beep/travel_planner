from dataclasses import dataclass, field

from app.data_sources.map_providers import MapRouteEstimate, MapRouteProviderResult, data_source_metadata
from app.models.schemas import GeoPoint, PlanType, SourceFailure, TransportMode, money
import pytest

from app.services.local_transfer_engine import (
    LocalTransferUnavailable,
    PlanningLocationResolverCache,
    PlanningRouteEstimatorCache,
    build_local_transfer_segment,
    enrich_local_transfer_segment,
)


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


def test_two_phase_transfer_publishes_selected_fact_before_alternatives(monkeypatch):
    monkeypatch.setenv("TRAVEL_TWO_PHASE_TRANSFER_ENABLED", "true")
    calls: list[TransportMode] = []

    def tracked_estimate(request, environment=None):
        calls.append(request.mode)
        return _estimate_for_mode(request, environment)

    selected = build_local_transfer_segment(
        segment_id="seg_two_phase",
        origin="上海虹桥站",
        destination="上海站",
        default_minutes=15,
        default_cost_minor=3200,
        selected_option_id="transfer_taxi",
        route_estimator=tracked_estimate,
    )

    assert calls == [TransportMode.TAXI]
    assert selected.option_id == "transfer_taxi"
    assert selected.available_options == ["transfer_taxi"]

    enriched = enrich_local_transfer_segment(selected, route_estimator=tracked_estimate)
    assert enriched.segment_id == selected.segment_id
    assert enriched.option_id == selected.option_id
    assert len(enriched.transfer_options) == 4


@pytest.mark.parametrize(
    ("origin_name", "destination_point"),
    [
        ("上海虹桥机场", GeoPoint(name="虹桥站", latitude=31.20, longitude=121.32)),
        ("上海虹桥站", GeoPoint(name="上海站", latitude=31.23, longitude=121.47)),
    ],
)
def test_walking_short_circuit_skips_inapplicable_network_calls(
    monkeypatch,
    origin_name,
    destination_point,
):
    monkeypatch.setenv("TRAVEL_WALKING_SHORT_CIRCUIT_ENABLED", "true")
    requested_modes: list[TransportMode] = []

    def resolve_location(query):
        if query == origin_name:
            return GeoPoint(name=query, latitude=31.20, longitude=121.32)
        return destination_point

    def tracked_estimate(request, environment=None):
        requested_modes.append(request.mode)
        return _estimate_for_mode(request, environment)

    build_local_transfer_segment(
        segment_id="seg_no_walk_network",
        origin=origin_name,
        destination="上海站",
        default_minutes=15,
        default_cost_minor=3200,
        route_estimator=tracked_estimate,
        location_resolver=resolve_location,
    )

    assert TransportMode.WALK not in requested_modes


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


def test_invalid_bus_response_does_not_block_other_local_transfer_modes():
    sink = _IssueSink()

    def isolated_estimate(request, environment=None):
        if request.mode == TransportMode.BUS:
            return MapRouteProviderResult(
                estimate=None,
                attempted_source_ids=["amap_route"],
                failure_message="amap_route: invalid bus cost field",
                error_code="MAP_ROUTE_RESPONSE_INVALID",
                query_status="UNAVAILABLE",
            )
        return _estimate_for_mode(request, environment)

    segment = build_local_transfer_segment(
        segment_id="seg_bus_invalid_cost",
        origin="上海虹桥站",
        destination="上海站",
        default_minutes=38,
        default_cost_minor=7800,
        selected_option_id="transfer_taxi",
        route_estimator=isolated_estimate,
        issue_sink=sink,
    )

    option_ids = {option.option_id for option in segment.transfer_options}
    assert {"transfer_taxi", "transfer_subway", "transfer_walk"}.issubset(option_ids)
    assert "transfer_bus" not in option_ids
    assert segment.route_status == "PRIMARY_VERIFIED"
    assert sink.missing == []
    assert sink.warnings == []
    assert any(failure["error_code"] == "MAP_ROUTE_RESPONSE_INVALID" for failure in sink.failures)


def test_planning_scope_caches_reuse_location_and_route_queries_for_identical_keys():
    location_calls = 0
    route_calls = 0

    def resolve_location(query):
        nonlocal location_calls
        location_calls += 1
        return GeoPoint(
            name=query,
            latitude=31.20 if "虹桥" in query else 31.23,
            longitude=121.32 if "虹桥" in query else 121.47,
        )

    def estimate_route(request, environment=None):
        nonlocal route_calls
        route_calls += 1
        return _estimate_for_mode(request, environment)

    location_cache = PlanningLocationResolverCache(resolve_location)
    route_cache = PlanningRouteEstimatorCache(estimate_route, provider_family="test-map-provider")
    arguments = {
        "origin": "上海虹桥站",
        "destination": "上海站",
        "default_minutes": 15,
        "default_cost_minor": 3200,
        "route_estimator": route_cache,
        "location_resolver": location_cache,
    }

    build_local_transfer_segment(segment_id="seg_cache_a", **arguments)
    build_local_transfer_segment(segment_id="seg_cache_b", **arguments)

    assert location_calls == 2
    assert route_calls == 4
    assert location_cache.misses == 2
    assert location_cache.hits == 2
    assert route_cache.misses == 4
    assert route_cache.hits == 4
