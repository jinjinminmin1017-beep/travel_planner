from app.data_sources.geocoding_providers import GeocodeCandidate, GeocodeProviderSearchResult, geocoding_data_source_metadata
from app.models.schemas import GeoPoint
from app.services.location_resolver import (
    airport_candidates_for_location,
    planning_nodes_for_request,
    resolve_location,
    resolve_location_point,
    station_candidates_for_location,
)


def test_station_and_airport_candidates_include_metadata():
    stations = station_candidates_for_location("北京国贸")
    airports = airport_candidates_for_location("青岛金水假日酒店")

    assert stations[0].station_name == "北京西"
    assert stations[0].city_name == "北京"
    assert stations[0].data_source.source_id == "internal_seed"
    assert stations[0].ranking_reasons
    assert airports[0].airport_name == "青岛胶东机场"
    assert airports[0].data_source.source_id == "internal_seed"


def test_location_resolver_marks_city_level_query_as_ambiguous():
    resolution = resolve_location("上海")

    assert resolution.status == "AMBIGUOUS"
    assert resolution.primary is None
    assert {candidate.city_name for candidate in resolution.candidates} == {"上海"}
    assert len(resolution.candidates) >= 2


def test_planning_nodes_cover_supported_and_known_unsupported_routes():
    supported = planning_nodes_for_request("北京国贸", "广州天河体育中心")
    unsupported = planning_nodes_for_request("成都春熙路", "深圳福田中心区")

    assert supported.supported is True
    assert supported.route_key == "北京_广州"
    assert supported.start_station == "北京西"
    assert supported.end_airport == "广州白云机场"
    assert unsupported.supported is False
    assert unsupported.route_key == "成都_深圳"
    assert unsupported.start_station == "成都东"
    assert unsupported.end_station == "深圳北"


def test_wuhan_destination_generates_station_and_airport_candidates():
    nodes = planning_nodes_for_request("上海静安寺", "武汉天地")

    assert nodes.route_key == "上海_武汉"
    assert nodes.start_station == "上海虹桥"
    assert nodes.end_station == "武汉"
    assert any(candidate.station_name == "汉口" for candidate in nodes.station_candidates)
    assert nodes.end_airport == "武汉天河机场"


def test_geocode_address_city_generates_catalog_transport_candidates(monkeypatch):
    def _fake_geocode(request, environment=None):
        return GeocodeProviderSearchResult(
            candidates=[
                GeocodeCandidate(
                    place_id="poi_1",
                    display_name="未知展馆, 江岸区, 武汉市, 湖北省, 中国",
                    point=GeoPoint(name="未知展馆", latitude=30.62, longitude=114.29),
                    address={"city": "武汉市", "state": "湖北省", "country": "中国"},
                    category="tourism",
                    place_type="attraction",
                    importance=0.5,
                    osm_type="node",
                    osm_id="1",
                    data_source=geocoding_data_source_metadata("nominatim_geocode", "Nominatim Search API"),
                )
            ],
            attempted_source_ids=["nominatim_geocode"],
        )

    monkeypatch.setattr("app.services.location_resolver.geocode_with_enabled_provider_result", _fake_geocode)

    stations = station_candidates_for_location("未知展馆")
    airports = airport_candidates_for_location("未知展馆")

    assert stations[0].station_name == "武汉"
    assert any(candidate.station_name == "汉口" for candidate in stations)
    assert airports[0].airport_name == "武汉天河机场"


def test_imported_12306_catalog_generates_non_seed_city_station_candidates():
    stations = station_candidates_for_location("长沙五一广场")

    assert stations
    assert stations[0].city_name == "长沙"
    assert stations[0].station_name == "长沙"
    assert stations[0].data_source.source_id == "rail_12306_station_catalog"
    assert stations[0].location.latitude is None
    assert stations[0].estimated_transfer_cost is None
    assert any("坐标" in reason for reason in stations[0].ranking_reasons)


def test_poi_and_station_points_are_not_overridden_by_city_aliases():
    pearl = resolve_location_point("上海东方明珠塔")
    hongqiao = resolve_location_point("上海虹桥站")
    chengdu_east = resolve_location_point("成都东站")
    taikoo = resolve_location_point("成都太古里")

    assert pearl.point and pearl.point.name == "上海东方明珠塔"
    assert hongqiao.point and hongqiao.point.name == "上海虹桥站"
    assert chengdu_east.point and chengdu_east.point.name == "成都东站"
    assert taikoo.point and taikoo.point.name == "成都太古里"
    assert round(pearl.point.longitude or 0, 3) == 121.500
    assert round(taikoo.point.longitude or 0, 3) == 104.083


def test_provider_aware_point_resolution_reuses_cached_search(monkeypatch):
    calls = []

    def _fake_geocode(request, environment=None):
        calls.append(request)
        return GeocodeProviderSearchResult(
            candidates=[
                GeocodeCandidate(
                    place_id="amap_poi_1",
                    display_name="测试新天地，武汉市江岸区",
                    point=GeoPoint(name="测试新天地", latitude=30.61, longitude=114.31),
                    address={"city": "武汉市", "district": "江岸区"},
                    category="商务住宅",
                    place_type="120000",
                    importance=None,
                    osm_type=None,
                    osm_id=None,
                    data_source=geocoding_data_source_metadata("amap_place_search", "AMap Place Search API", authority_level="A"),
                )
            ],
            attempted_source_ids=["amap_geocode", "amap_place_search"],
        )

    monkeypatch.setattr("app.services.location_resolver.geocode_with_enabled_provider_result", _fake_geocode)

    first = resolve_location_point("武汉测试新天地-缓存用例", city_context="武汉")
    second = resolve_location_point("武汉测试新天地-缓存用例", city_context="武汉")

    assert first.status == "RESOLVED"
    assert first.source_id == "amap_place_search"
    assert second.point == first.point
    assert len(calls) == 1


def test_catalog_node_without_coordinates_continues_to_online_resolution(monkeypatch):
    calls = []

    def _fake_geocode(request, environment=None):
        calls.append(request)
        return GeocodeProviderSearchResult(
            candidates=[
                GeocodeCandidate(
                    place_id="amap_station_1",
                    display_name="温州南站，温州市瓯海区",
                    point=GeoPoint(name="温州南站", latitude=27.9803, longitude=120.5856),
                    address={"city": "温州市", "district": "瓯海区"},
                    category="交通设施服务",
                    place_type="150200",
                    importance=None,
                    osm_type=None,
                    osm_id=None,
                    data_source=geocoding_data_source_metadata("amap_place_search", "AMap Place Search API", authority_level="A"),
                )
            ],
            attempted_source_ids=["amap_geocode", "amap_place_search"],
        )

    monkeypatch.setattr("app.services.location_resolver.geocode_with_enabled_provider_result", _fake_geocode)

    resolution = resolve_location_point("温州南站", city_context="温州")

    assert resolution.status == "RESOLVED"
    assert resolution.point and resolution.point.latitude == 27.9803
    assert resolution.source_id == "amap_place_search"
    assert len(calls) == 1


def test_provider_aware_point_resolution_does_not_pick_first_ambiguous_candidate(monkeypatch):
    def _fake_geocode(request, environment=None):
        candidates = [
            GeocodeCandidate(
                place_id=f"poi_{index}",
                display_name=f"同名广场，武汉市{district}",
                point=GeoPoint(name="同名广场", latitude=30.60 + index / 100, longitude=114.30 + index / 100),
                address={"city": "武汉市", "district": district},
                category=None,
                place_type=None,
                importance=None,
                osm_type=None,
                osm_id=None,
                data_source=geocoding_data_source_metadata("amap_place_search", "AMap Place Search API", authority_level="A"),
            )
            for index, district in enumerate(("江岸区", "洪山区"), start=1)
        ]
        return GeocodeProviderSearchResult(candidates=candidates, attempted_source_ids=["amap_geocode", "amap_place_search"], error_code="MAP_LOCATION_AMBIGUOUS")

    monkeypatch.setattr("app.services.location_resolver.geocode_with_enabled_provider_result", _fake_geocode)

    resolution = resolve_location_point("武汉同名广场-歧义用例", city_context="武汉")

    assert resolution.status == "AMBIGUOUS"
    assert resolution.point is None
    assert resolution.error_code == "MAP_LOCATION_AMBIGUOUS"
    assert len(resolution.candidates) == 2


def test_city_aliases_do_not_match_inside_specific_poi_queries():
    resolution = resolve_location("上海未知展馆")

    assert resolution.primary is None
    assert all(candidate.name != "上海市区" for candidate in resolution.candidates)
