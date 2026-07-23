from app.data_sources.transport_catalog_providers import city_pinyin_aliases_from_rail_nodes, merge_transport_nodes, normalize_transport_node_item, parse_12306_station_catalog, parse_ourairports_catalog
from app.services.location_resolver import (
    airport_candidate_for_iata,
    airport_candidates_for_city,
    airport_iata_for_candidate,
)


def test_parse_12306_station_catalog_uses_official_city_field():
    payload = "var station_names ='@bjb|北京北|VAP|beijingbei|bjb|0|0357|北京|||@csh|长沙|CSQ|changsha|cs|1|0900|长沙|||';"

    nodes = parse_12306_station_catalog(payload, imported_at="2026-06-23T00:00:00+00:00")

    assert len(nodes) == 2
    assert nodes[0].node_id == "rail_12306_vap"
    assert nodes[0].node_name == "北京北"
    assert nodes[0].city_name == "北京"
    assert nodes[0].station_code == "VAP"
    assert nodes[0].latitude is None
    assert nodes[0].coordinate_quality == "MISSING"
    assert nodes[1].hub_rank == 1


def test_parse_ourairports_catalog_filters_china_iata_airports():
    payload = "\n".join(
        [
            '"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","gps_code","iata_code"',
            '"1","ZBAA","large_airport","Beijing Capital International Airport","40.080101","116.584999","116","AS","CN","CN-11","Beijing","yes","ZBAA","PEK"',
            '"2","KJFK","large_airport","John F Kennedy International Airport","40.639801","-73.7789","13","NA","US","US-NY","New York","yes","KJFK","JFK"',
            '"3","CN-0001","small_airport","Small Field","30.1","120.1","","AS","CN","CN-33","Hangzhou","no","",""',
        ]
    )

    nodes = parse_ourairports_catalog(payload, imported_at="2026-06-23T00:00:00+00:00")

    assert len(nodes) == 1
    assert nodes[0].node_id == "airport_ourairports_zbaa"
    assert nodes[0].city_name == "Beijing"
    assert nodes[0].iata_code == "PEK"
    assert nodes[0].latitude == 40.080101
    assert nodes[0].coordinate_quality == "PROVIDER"


def test_parse_ourairports_catalog_maps_english_city_from_rail_pinyin_aliases():
    rail_nodes = parse_12306_station_catalog("var station_names ='@sya|三亚|SEQ|sanya|sy|0|1234|三亚|||';")
    aliases = city_pinyin_aliases_from_rail_nodes(rail_nodes)
    payload = "\n".join(
        [
            '"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","gps_code","iata_code"',
            '"1","ZJSY","medium_airport","Sanya Phoenix International Airport","18.3029","109.412","92","AS","CN","CN-46","Sanya","yes","ZJSY","SYX"',
        ]
    )

    nodes = parse_ourairports_catalog(payload, imported_at="2026-06-23T00:00:00+00:00", city_name_aliases=aliases)

    assert nodes[0].city_name == "三亚"
    assert nodes[0].iata_code == "SYX"


def test_merge_transport_nodes_preserves_seed_and_adds_imported_catalog():
    existing = [
        {
            "node_id": "sha_hongqiao",
            "node_name": "上海虹桥",
            "city_name": "上海",
            "latitude": 31.2,
            "longitude": 121.3269,
            "hub_rank": 1,
            "aliases": ["上海虹桥站"],
        }
    ]
    imported = parse_12306_station_catalog("var station_names ='@csh|长沙|CSQ|changsha|cs|1|0900|长沙|||';")

    merged = merge_transport_nodes(existing, imported)

    assert len(merged["stations"]) == 2
    assert merged["stations"][0]["node_name"] == "上海虹桥"
    assert merged["stations"][0]["node_type"] == "RAIL_STATION"
    assert merged["stations"][0]["source_id"] == "internal_seed"
    assert merged["stations"][0]["source_name"] == "Internal Transport Node Seed"
    assert merged["stations"][0]["source_version"] == "manual"
    assert merged["stations"][0]["station_code"] is None
    assert merged["stations"][0]["iata_code"] is None
    assert merged["stations"][0]["icao_code"] is None
    assert merged["stations"][0]["license_status"] == "APPROVED"
    assert merged["stations"][0]["commercial_allowed"] is False
    assert merged["stations"][0]["coordinate_quality"] == "MANUAL"
    assert merged["stations"][1]["node_name"] == "长沙"
    assert "rail_12306_station_catalog" in merged["metadata"]["sources"]


def test_normalize_transport_node_item_adds_full_schema_to_seed_airport():
    normalized = normalize_transport_node_item(
        {
            "node_id": "sha_pudong_airport",
            "node_name": "上海浦东机场",
            "city_name": "上海",
            "latitude": 31.1443,
            "longitude": 121.8083,
            "hub_rank": 1,
            "aliases": ["浦东机场"],
        },
        "AIRPORT",
    )

    assert normalized == {
        "node_id": "sha_pudong_airport",
        "node_type": "AIRPORT",
        "node_name": "上海浦东机场",
        "city_name": "上海",
        "latitude": 31.1443,
        "longitude": 121.8083,
        "hub_rank": 1,
        "aliases": ["浦东机场"],
        "station_code": None,
        "iata_code": "PVG",
        "icao_code": None,
        "source_id": "internal_seed",
        "source_name": "Internal Transport Node Seed",
        "source_version": "manual",
        "imported_at": None,
        "license_status": "APPROVED",
        "commercial_allowed": False,
        "coordinate_quality": "MANUAL",
    }


def test_shanghai_airport_candidates_are_canonical_before_limit():
    candidates = airport_candidates_for_city("上海", limit=2)
    iatas = [airport_iata_for_candidate(candidate) for candidate in candidates]

    assert set(iatas) == {"SHA", "PVG"}
    assert len(iatas) == len(set(iatas))
    assert airport_candidate_for_iata("PVG", expected_city="上海") is not None
    assert airport_candidate_for_iata("PVG", expected_city="大连") is None
