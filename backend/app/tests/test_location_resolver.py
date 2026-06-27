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

    assert pearl and pearl.name == "上海东方明珠塔"
    assert hongqiao and hongqiao.name == "上海虹桥站"
    assert chengdu_east and chengdu_east.name == "成都东站"
    assert taikoo and taikoo.name == "成都太古里"
    assert round(pearl.longitude or 0, 3) == 121.500
    assert round(taikoo.longitude or 0, 3) == 104.083


def test_city_aliases_do_not_match_inside_specific_poi_queries():
    resolution = resolve_location("上海未知展馆")

    assert resolution.primary is None
    assert all(candidate.name != "上海市区" for candidate in resolution.candidates)
