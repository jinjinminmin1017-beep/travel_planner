from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.data_sources.geocoding_providers import GeocodeCandidate, GeocodeRequest, geocode_with_enabled_provider_result
from app.models.schemas import AirportCandidate, DataSourceMetadata, DataSourceType, GeoPoint, StationCandidate, TransportMode, money, now_timepoint


@dataclass(frozen=True)
class LocationRecord:
    name: str
    city_name: str
    point: GeoPoint
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    node_type: str
    node_name: str
    city_name: str
    point: GeoPoint
    hub_rank: int
    aliases: tuple[str, ...] = ()
    station_code: str | None = None
    iata_code: str | None = None
    source_id: str = "internal_calc"
    source_name: str = "Internal Location Catalog"
    license_status: str = "APPROVED"
    commercial_allowed: bool = False
    coordinate_quality: str = "PROVIDER"


@dataclass(frozen=True)
class LocationResolution:
    query: str
    status: str
    primary: LocationRecord | None
    candidates: list[LocationRecord]
    attempted_source_ids: list[str]
    failure_message: str | None = None


@dataclass(frozen=True)
class PlanningRouteNodes:
    route_key: str
    supported: bool
    city_origin: str
    city_destination: str
    start_station: str
    end_station: str
    start_airport: str
    end_airport: str
    rail_train: str
    flight_no: str
    station_candidates: list[StationCandidate]
    airport_candidates: list[AirportCandidate]


INTERNAL_LOCATION_SOURCE = DataSourceMetadata(
    source_id="internal_calc",
    source_name="Internal Location Catalog",
    source_type=DataSourceType.INTERNAL_CALCULATION,
    authority_level="B",
    license_status="APPROVED",
    commercial_allowed=False,
    fetched_at=now_timepoint(),
    cacheable=True,
)

TRANSPORT_NODE_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "transport_nodes.json"


LOCATIONS: tuple[LocationRecord, ...] = (
    LocationRecord("上海嘉定南翔格林公馆", "上海", GeoPoint(name="上海嘉定南翔格林公馆", latitude=31.2955, longitude=121.3232), ("南翔格林公馆", "上海南翔")),
    LocationRecord("上海东方明珠塔", "上海", GeoPoint(name="上海东方明珠塔", latitude=31.239703, longitude=121.499718), ("东方明珠塔", "东方明珠", "上海东方明珠")),
    LocationRecord("上海市区", "上海", GeoPoint(name="上海市区", latitude=31.2304, longitude=121.4737), ("上海", "Shanghai")),
    LocationRecord("青岛金水假日酒店", "青岛", GeoPoint(name="青岛金水假日酒店", latitude=36.1615, longitude=120.4351), ("金水假日酒店", "青岛酒店")),
    LocationRecord("青岛市区", "青岛", GeoPoint(name="青岛市区", latitude=36.0662, longitude=120.3826), ("青岛", "Qingdao")),
    LocationRecord("北京国贸", "北京", GeoPoint(name="北京国贸", latitude=39.9097, longitude=116.4619), ("北京市朝阳区国贸", "国贸", "Beijing")),
    LocationRecord("广州天河体育中心", "广州", GeoPoint(name="广州天河体育中心", latitude=23.1369, longitude=113.3266), ("广州", "天河体育中心", "Guangzhou")),
    LocationRecord("成都太古里", "成都", GeoPoint(name="成都太古里", latitude=30.652509, longitude=104.082798), ("太古里", "成都远洋太古里")),
    LocationRecord("成都春熙路", "成都", GeoPoint(name="成都春熙路", latitude=30.6570, longitude=104.0808), ("成都", "春熙路", "Chengdu")),
    LocationRecord("深圳福田中心区", "深圳", GeoPoint(name="深圳福田中心区", latitude=22.5431, longitude=114.0579), ("深圳", "福田中心区", "Shenzhen")),
    LocationRecord("杭州西湖", "杭州", GeoPoint(name="杭州西湖", latitude=30.2420, longitude=120.1500), ("杭州", "西湖", "Hangzhou")),
    LocationRecord("西安钟楼", "西安", GeoPoint(name="西安钟楼", latitude=34.2610, longitude=108.9420), ("西安", "钟楼", "Xi'an", "Xian")),
    LocationRecord("武汉天地", "武汉", GeoPoint(name="武汉天地", latitude=30.6105, longitude=114.3115), ("武汉", "武汉市区", "Wuhan")),
)


def _normalize_city_name(value: str) -> str:
    city = value.strip().replace(" ", "")
    suffixes = ("特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "省", "市", "地区", "盟")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if city.endswith(suffix) and len(city) > len(suffix):
                city = city[: -len(suffix)]
                changed = True
    return city


def _load_transport_nodes(section: str) -> list[NodeRecord]:
    with TRANSPORT_NODE_CATALOG_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    items = payload.get(section)
    if not isinstance(items, list):
        raise ValueError(f"transport node catalog section is missing: {section}")
    return [_node_record_from_catalog_item(item, section) for item in items]


def _node_record_from_catalog_item(item: Any, section: str) -> NodeRecord:
    if not isinstance(item, dict):
        raise ValueError(f"transport node catalog item is not an object: {section}")
    node_name = str(item["node_name"])
    node_type = str(item.get("node_type") or ("AIRPORT" if section == "airports" else "RAIL_STATION"))
    latitude = item.get("latitude")
    longitude = item.get("longitude")
    return NodeRecord(
        node_id=str(item["node_id"]),
        node_type=node_type,
        node_name=node_name,
        city_name=_normalize_city_name(str(item["city_name"])) or str(item["city_name"]),
        point=GeoPoint(
            name=f"{node_name}{'站' if section == 'stations' and not node_name.endswith('站') else ''}",
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
        ),
        hub_rank=int(item["hub_rank"]),
        aliases=tuple(str(alias) for alias in item.get("aliases", []) if alias),
        station_code=str(item["station_code"]) if item.get("station_code") else None,
        iata_code=str(item["iata_code"]) if item.get("iata_code") else None,
        source_id=str(item.get("source_id") or "internal_calc"),
        source_name=str(item.get("source_name") or "Internal Location Catalog"),
        license_status=str(item.get("license_status") or "APPROVED"),
        commercial_allowed=bool(item.get("commercial_allowed", False)),
        coordinate_quality=str(item.get("coordinate_quality") or "PROVIDER"),
    )


STATIONS = tuple(_load_transport_nodes("stations"))
AIRPORTS = tuple(_load_transport_nodes("airports"))


def resolve_location(query: str, environment: str | None = None) -> LocationResolution:
    normalized = _normalize(query)
    matches = [record for record in LOCATIONS if _matches_location(record, normalized)]
    if len(matches) == 1:
        return LocationResolution(query=query, status="RESOLVED", primary=matches[0], candidates=matches, attempted_source_ids=["internal_calc"])
    if len(matches) > 1:
        return LocationResolution(query=query, status="AMBIGUOUS", primary=None, candidates=matches, attempted_source_ids=["internal_calc"])

    geocode_result = geocode_with_enabled_provider_result(GeocodeRequest(query=query, country_codes="cn", limit=3), environment)
    if geocode_result.candidates:
        candidates = [
            LocationRecord(candidate.display_name, _city_from_geocode_candidate(candidate), candidate.point, ())
            for candidate in geocode_result.candidates
        ]
        status = "RESOLVED" if len(candidates) == 1 else "AMBIGUOUS"
        return LocationResolution(query=query, status=status, primary=candidates[0] if status == "RESOLVED" else None, candidates=candidates, attempted_source_ids=geocode_result.attempted_source_ids)
    return LocationResolution(query=query, status="UNSUPPORTED", primary=None, candidates=[], attempted_source_ids=geocode_result.attempted_source_ids or ["internal_calc"], failure_message=geocode_result.failure_message)


def resolve_location_point(place: str) -> GeoPoint | None:
    node = _find_node(place)
    if node:
        return node.point
    record = _find_location_record(place)
    return record.point if record else None


def resolve_location_city(place: str, environment: str | None = None) -> str | None:
    node = _find_node(place)
    if node:
        return node.city_name
    record = _find_location_record(place)
    if record:
        return record.city_name
    city = _infer_city_from_text(place)
    if city:
        return city
    resolution = resolve_location(place, environment)
    if resolution.primary and resolution.primary.city_name:
        return resolution.primary.city_name
    cities = {candidate.city_name for candidate in resolution.candidates if candidate.city_name}
    if len(cities) == 1:
        return next(iter(cities))
    return None


def station_candidates_for_location(place: str, limit: int = 3, environment: str | None = None) -> list[StationCandidate]:
    city, point = _resolve_city_and_point(place, environment)
    if point and not _has_coordinates(point):
        point = None
    if not point and city:
        point = _city_reference_point(city)
    if point and not _has_coordinates(point):
        point = None
    if not city:
        return []
    return [_station_candidate(record, point) for record in _rank_nodes(STATIONS, city, point)[:limit]]


def airport_candidates_for_location(place: str, limit: int = 2, environment: str | None = None) -> list[AirportCandidate]:
    city, point = _resolve_city_and_point(place, environment)
    if point and not _has_coordinates(point):
        point = None
    if not point and city:
        point = _city_reference_point(city)
    if point and not _has_coordinates(point):
        point = None
    if not city:
        return []
    return [_airport_candidate(record, point) for record in _rank_nodes(AIRPORTS, city, point)[:limit]]


def airport_candidates_for_city(city: str, limit: int = 2) -> list[AirportCandidate]:
    point = _city_reference_point(city)
    if point and not _has_coordinates(point):
        point = None
    return [_airport_candidate(record, point) for record in _rank_nodes(AIRPORTS, city, point)[:limit]]


def airport_iata_for_candidate(candidate: AirportCandidate) -> str | None:
    for record in AIRPORTS:
        if record.node_id == candidate.airport_id and record.iata_code:
            return record.iata_code
    normalized_name = _normalize(candidate.airport_name)
    for record in AIRPORTS:
        if record.city_name == candidate.city_name and _normalize(record.node_name) == normalized_name and record.iata_code:
            return record.iata_code
    return None


def transfer_station_candidates_between(origin_city: str, destination_city: str, limit: int = 6) -> list[StationCandidate]:
    origin_point = _city_reference_point(origin_city)
    destination_point = _city_reference_point(destination_city)
    excluded = {origin_city, destination_city, ""}
    candidates = [node for node in STATIONS if node.city_name not in excluded]
    if origin_point and destination_point:
        candidates = sorted(
            candidates,
            key=lambda node: (
                _transfer_station_detour_score(node, origin_point, destination_point),
                node.hub_rank,
                0 if node.source_id == "internal_calc" else 1,
                node.node_name,
            ),
        )
    else:
        candidates = sorted(
            candidates,
            key=lambda node: (
                node.hub_rank,
                0 if node.source_id == "internal_calc" else 1,
                0 if _has_coordinates(node.point) else 1,
                node.node_name,
            ),
        )
    deduped: list[NodeRecord] = []
    seen_cities: set[str] = set()
    seen_names: set[str] = set()
    for node in candidates:
        name_key = _normalize(node.node_name)
        if node.city_name in seen_cities or name_key in seen_names:
            continue
        seen_cities.add(node.city_name)
        seen_names.add(name_key)
        deduped.append(node)
        if len(deduped) >= limit:
            break
    return [_station_candidate(node, _city_reference_point(node.city_name)) for node in deduped]


def planning_nodes_for_request(origin: str, destination: str) -> PlanningRouteNodes:
    origin_stations = station_candidates_for_location(origin)
    destination_stations = station_candidates_for_location(destination)
    origin_airports = airport_candidates_for_location(origin)
    destination_airports = airport_candidates_for_location(destination)
    origin_city = (origin_stations[0].city_name if origin_stations else resolve_location_city(origin)) or ""
    destination_city = (destination_stations[0].city_name if destination_stations else resolve_location_city(destination)) or ""
    route_key = f"{origin_city}_{destination_city}"
    supported = route_key in {"上海_青岛", "北京_广州"}
    rail_train = "G79" if route_key == "北京_广州" else "G234"
    flight_no = "CZ3102" if route_key == "北京_广州" else "MU5511"
    return PlanningRouteNodes(
        route_key=route_key,
        supported=supported,
        city_origin=_display_origin(origin, origin_city),
        city_destination=_display_destination(destination, destination_city),
        start_station=origin_stations[0].station_name if origin_stations else "",
        end_station=destination_stations[0].station_name if destination_stations else "",
        start_airport=origin_airports[0].airport_name if origin_airports else "",
        end_airport=destination_airports[0].airport_name if destination_airports else "",
        rail_train=rail_train,
        flight_no=flight_no,
        station_candidates=[*origin_stations, *destination_stations],
        airport_candidates=[*origin_airports, *destination_airports],
    )


def nearby_transit_stop(place: str, mode: TransportMode, side: str) -> str:
    city = resolve_location_city(place)
    if mode == TransportMode.SUBWAY:
        if "机场" in place:
            return f"{place.replace('机场', '')}机场站"
        if place.endswith("站"):
            return place
        if city:
            return f"{city}{'中心' if side == 'origin' else '枢纽'}地铁站"
        return f"{place}附近地铁站"
    if city:
        return f"{place}附近公交站"
    return f"{place}附近公交站"


def _station_candidate(record: NodeRecord, origin_point: GeoPoint | None) -> StationCandidate:
    distance = _distance_meters(origin_point, record.point) if origin_point and _has_coordinates(record.point) else None
    if distance is None:
        transfer_minutes = 0
        transfer_cost = None
        ranking_reasons = [f"城市匹配：{record.city_name}", f"枢纽优先级：{record.hub_rank}", "站点目录未提供可验证坐标，暂按枢纽等级排序。"]
    else:
        transfer_minutes = max(12, int(distance / 550))
        transfer_cost = money(max(600, int(distance / 1000 * 250)), estimated=True)
        ranking_reasons = [f"城市匹配：{record.city_name}", f"枢纽优先级：{record.hub_rank}", f"距输入地点约 {round(distance / 1000, 1)} km"]
    return StationCandidate(
        station_id=record.node_id,
        station_name=record.node_name,
        city_name=record.city_name,
        location=record.point,
        estimated_transfer_duration_minutes=transfer_minutes,
        estimated_transfer_cost=transfer_cost,
        ranking_reasons=ranking_reasons,
        data_source=_node_data_source(record, DataSourceType.RAIL),
    )


def _airport_candidate(record: NodeRecord, origin_point: GeoPoint | None) -> AirportCandidate:
    distance = _distance_meters(origin_point, record.point) if origin_point and _has_coordinates(record.point) else None
    if distance is None:
        transfer_minutes = 0
        transfer_cost = None
        ranking_reasons = [f"城市匹配：{record.city_name}", f"机场优先级：{record.hub_rank}", "机场目录未提供可验证坐标，暂按枢纽等级排序。"]
    else:
        transfer_minutes = max(25, int(distance / 650))
        transfer_cost = money(max(5000, int(distance / 1000 * 350)), estimated=True)
        ranking_reasons = [f"城市匹配：{record.city_name}", f"机场优先级：{record.hub_rank}", f"距输入地点约 {round(distance / 1000, 1)} km"]
    return AirportCandidate(
        airport_id=record.node_id,
        airport_name=record.node_name,
        city_name=record.city_name,
        location=record.point,
        estimated_transfer_duration_minutes=transfer_minutes,
        estimated_transfer_cost=transfer_cost,
        ranking_reasons=ranking_reasons,
        data_source=_node_data_source(record, DataSourceType.FLIGHT),
    )


def _rank_nodes(nodes: tuple[NodeRecord, ...], city: str, point: GeoPoint | None) -> list[NodeRecord]:
    city_nodes = [node for node in nodes if node.city_name == city]
    ranked = sorted(
        city_nodes,
        key=lambda node: (
            node.hub_rank,
            0 if node.source_id in {"internal_calc", "internal_seed"} else 1,
            0 if _has_coordinates(node.point) else 1,
            _distance_meters(point, node.point) if point and _has_coordinates(node.point) else 0,
        ),
    )
    deduped: list[NodeRecord] = []
    seen_names: set[str] = set()
    for node in ranked:
        key = _normalize(node.node_name)
        if key in seen_names:
            continue
        seen_names.add(key)
        deduped.append(node)
    return deduped


def _node_data_source(record: NodeRecord, source_type: DataSourceType) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=record.source_id,
        source_name=record.source_name,
        source_type=source_type,
        authority_level="B",
        license_status=record.license_status if record.license_status in {"APPROVED", "PENDING_REVIEW", "NOT_APPROVED"} else "PENDING_REVIEW",
        commercial_allowed=record.commercial_allowed,
        fetched_at=now_timepoint(),
        cacheable=True,
    )


def _city_reference_point(city: str) -> GeoPoint | None:
    for record in LOCATIONS:
        if record.city_name == city and _has_coordinates(record.point):
            return record.point
    for node in (*STATIONS, *AIRPORTS):
        if node.city_name == city and _has_coordinates(node.point):
            return node.point
    return None


def _has_coordinates(point: GeoPoint) -> bool:
    return point.latitude is not None and point.longitude is not None


def _resolve_city_and_point(place: str, environment: str | None = None) -> tuple[str | None, GeoPoint | None]:
    node = _find_node(place)
    if node:
        return node.city_name, node.point

    record = _find_location_record(place)
    if record:
        return record.city_name, record.point

    text_city = _infer_city_from_text(place)
    if text_city:
        return text_city, _city_reference_point(text_city)

    resolution = resolve_location(place, environment)
    if resolution.primary:
        return resolution.primary.city_name or None, resolution.primary.point

    cities = {candidate.city_name for candidate in resolution.candidates if candidate.city_name}
    if len(cities) == 1:
        city = next(iter(cities))
        point = next((candidate.point for candidate in resolution.candidates if candidate.city_name == city), None)
        return city, point

    return None, None


def _city_from_geocode_candidate(candidate: GeocodeCandidate) -> str:
    address_city_keys = (
        "city",
        "town",
        "municipality",
        "county",
        "state_district",
        "state",
        "province",
    )
    known_cities = _known_city_names()
    for key in address_city_keys:
        city = _normalize_city_name(candidate.address.get(key, ""))
        if city in known_cities:
            return city
    return _infer_city_from_text(candidate.display_name) or ""


def _infer_city_from_text(value: str) -> str | None:
    normalized = _normalize(value)
    for city in sorted(_known_city_names(), key=len, reverse=True):
        if _normalize(city) in normalized:
            return city
    return None


def _known_city_names() -> set[str]:
    cities = {record.city_name for record in LOCATIONS}
    cities.update(node.city_name for node in (*STATIONS, *AIRPORTS))
    return cities


def _find_location_record(place: str) -> LocationRecord | None:
    normalized = _normalize(place)
    exact = [record for record in LOCATIONS if _normalize(record.name) == normalized or normalized in {_normalize(alias) for alias in record.aliases}]
    if exact:
        return exact[0]
    contains = [
        record
        for record in LOCATIONS
        if _normalize(record.name) in normalized
        or any(_is_specific_alias_match(record, alias, normalized) for alias in record.aliases)
    ]
    return contains[0] if len(contains) == 1 else None


def _is_specific_alias_match(record: LocationRecord, alias: str, normalized_query: str) -> bool:
    normalized_alias = _normalize(alias)
    if not normalized_alias or normalized_alias not in normalized_query:
        return False
    if normalized_alias == _normalize(record.city_name):
        return False
    if normalized_alias.lower() in {record.city_name.lower(), _normalize(record.city_name).lower()}:
        return False
    if len(normalized_alias) < 3:
        return False
    return True


def _find_node(place: str) -> NodeRecord | None:
    normalized = _normalize(place)
    for node in (*STATIONS, *AIRPORTS):
        names = {_normalize(node.node_name), _normalize(f"{node.node_name}站"), _normalize(f"{node.node_name}机场"), *{_normalize(alias) for alias in node.aliases}}
        if normalized in names:
            return node
    return None


def _matches_location(record: LocationRecord, normalized: str) -> bool:
    values = {_normalize(record.name), _normalize(record.city_name), *{_normalize(alias) for alias in record.aliases}}
    return normalized in values or any(value and value in normalized for value in values if len(value) >= 3)


def _normalize(value: str) -> str:
    return value.strip().replace("市", "").replace(" ", "")


def _display_origin(origin: str, city: str) -> str:
    record = _find_location_record(origin)
    if record and record.name.endswith("市区"):
        return f"{city}市区"
    return record.name if record else origin


def _display_destination(destination: str, city: str) -> str:
    record = _find_location_record(destination)
    if record and record.name.endswith("市区"):
        return f"{city}市区"
    return record.name if record else destination


def _distance_meters(a: GeoPoint, b: GeoPoint) -> int:
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        return 0
    radius = 6371000
    lat1 = math.radians(a.latitude)
    lat2 = math.radians(b.latitude)
    dlat = math.radians(b.latitude - a.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return int(radius * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav)))


def _transfer_station_detour_score(node: NodeRecord, origin_point: GeoPoint, destination_point: GeoPoint) -> int:
    if not _has_coordinates(node.point):
        return 10**12
    direct = _distance_meters(origin_point, destination_point)
    via = _distance_meters(origin_point, node.point) + _distance_meters(node.point, destination_point)
    return max(0, via - direct)
