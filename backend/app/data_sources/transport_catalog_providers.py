from __future__ import annotations

import csv
import io
import json
import re
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.request import Request, urlopen


RAIL_12306_STATION_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
OURAIRPORTS_AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
CONTROLLED_SEED_AIRPORT_IATA: dict[str, str] = {
    "sha_hongqiao_airport": "SHA",
    "sha_pudong_airport": "PVG",
    "tao_jiaodong_airport": "TAO",
    "pek_capital_airport": "PEK",
    "pek_daxing_airport": "PKX",
    "can_baiyun_airport": "CAN",
    "ctu_tianfu_airport": "TFU",
    "szx_baoan_airport": "SZX",
    "hgh_xiaoshan_airport": "HGH",
    "sia_xianyang_airport": "XIY",
    "wuh_tianhe_airport": "WUH",
}


@dataclass(frozen=True)
class TransportCatalogNode:
    node_id: str
    node_type: str
    node_name: str
    city_name: str
    latitude: float | None
    longitude: float | None
    hub_rank: int
    aliases: list[str]
    station_code: str | None
    iata_code: str | None
    icao_code: str | None
    source_id: str
    source_name: str
    source_version: str
    imported_at: str
    license_status: str
    commercial_allowed: bool
    coordinate_quality: str

    def to_json(self) -> dict:
        return asdict(self)


class CatalogProviderError(RuntimeError):
    pass


def fetch_text(url: str, *, timeout_seconds: int = 30, insecure: bool = False) -> str:
    request = Request(url, headers={"User-Agent": "AITravelPlanner/0.1"})
    context = ssl._create_unverified_context() if insecure else None
    with urlopen(request, timeout=timeout_seconds, context=context) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_12306_station_catalog(payload: str, *, imported_at: str | None = None, source_version: str = "station_name.js") -> list[TransportCatalogNode]:
    match = re.search(r"station_names\s*=\s*'(?P<body>.*?)'", payload, re.S)
    if not match:
        raise CatalogProviderError("12306 station catalog payload does not contain station_names")
    imported = imported_at or _utc_now_iso()
    nodes: list[TransportCatalogNode] = []
    for raw_entry in match.group("body").split("@"):
        if not raw_entry:
            continue
        fields = raw_entry.split("|")
        if len(fields) < 8:
            continue
        station_name = fields[1].strip()
        station_code = fields[2].strip()
        pinyin = fields[3].strip()
        short_pinyin = fields[4].strip()
        city_name = _normalize_city_name(fields[7].strip() or _city_from_station_name(station_name))
        if not station_name or not station_code or not city_name:
            continue
        aliases = _unique_non_empty([f"{station_name}站", station_code, pinyin, short_pinyin])
        nodes.append(
            TransportCatalogNode(
                node_id=f"rail_12306_{station_code.lower()}",
                node_type="RAIL_STATION",
                node_name=station_name,
                city_name=city_name,
                latitude=None,
                longitude=None,
                hub_rank=_station_hub_rank(station_name, city_name),
                aliases=aliases,
                station_code=station_code,
                iata_code=None,
                icao_code=None,
                source_id="rail_12306_station_catalog",
                source_name="12306 Station Name Catalog",
                source_version=source_version,
                imported_at=imported,
                license_status="PENDING_REVIEW",
                commercial_allowed=False,
                coordinate_quality="MISSING",
            )
        )
    return nodes


def parse_ourairports_catalog(
    payload: str,
    *,
    imported_at: str | None = None,
    source_version: str = "airports.csv",
    city_name_aliases: dict[str, str] | None = None,
) -> list[TransportCatalogNode]:
    imported = imported_at or _utc_now_iso()
    nodes: list[TransportCatalogNode] = []
    reader = csv.DictReader(io.StringIO(payload))
    for row in reader:
        if row.get("iso_country") != "CN":
            continue
        iata_code = (row.get("iata_code") or "").strip()
        airport_type = (row.get("type") or "").strip()
        scheduled_service = row.get("scheduled_service") == "yes"
        latitude = _optional_float(row.get("latitude_deg"))
        longitude = _optional_float(row.get("longitude_deg"))
        if not iata_code or not scheduled_service or latitude is None or longitude is None:
            continue
        city_name = _normalize_airport_city_name((row.get("municipality") or "").strip(), city_name_aliases or {})
        airport_name = (row.get("name") or "").strip()
        ident = (row.get("ident") or "").strip()
        if not city_name or not airport_name or not ident:
            continue
        aliases = _unique_non_empty([iata_code, ident, airport_name])
        nodes.append(
            TransportCatalogNode(
                node_id=f"airport_ourairports_{ident.lower().replace('-', '_')}",
                node_type="AIRPORT",
                node_name=airport_name,
                city_name=city_name,
                latitude=latitude,
                longitude=longitude,
                hub_rank=_airport_hub_rank(airport_type, scheduled_service),
                aliases=aliases,
                station_code=None,
                iata_code=iata_code or None,
                icao_code=ident if ident.startswith("Z") else None,
                source_id="ourairports_airport_catalog",
                source_name="OurAirports Airports CSV",
                source_version=source_version,
                imported_at=imported,
                license_status="APPROVED",
                commercial_allowed=True,
                coordinate_quality="PROVIDER",
            )
        )
    return nodes


def city_pinyin_aliases_from_rail_nodes(nodes: Iterable[TransportCatalogNode]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in nodes:
        if node.node_type != "RAIL_STATION" or node.node_name != node.city_name:
            continue
        for alias in node.aliases:
            normalized = _normalize_ascii_key(alias)
            if normalized and normalized.isascii() and not any(ch.isdigit() for ch in normalized):
                aliases.setdefault(normalized, node.city_name)
    return aliases


def merge_transport_nodes(existing: Iterable[dict], imported: Iterable[TransportCatalogNode]) -> dict[str, list[dict]]:
    stations: list[dict] = []
    airports: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for item in existing:
        node_type = _item_node_type(item)
        normalized_item = normalize_transport_node_item(item, node_type)
        key = _dedupe_key(normalized_item, node_type)
        if key in seen:
            continue
        seen.add(key)
        if node_type == "AIRPORT":
            airports.append(normalized_item)
        else:
            stations.append(normalized_item)

    for node in imported:
        item = node.to_json()
        key = _dedupe_key(item, node.node_type)
        if key in seen:
            continue
        seen.add(key)
        if node.node_type == "AIRPORT":
            airports.append(item)
        else:
            stations.append(item)

    return {
        "metadata": {
            "schema_version": "1.0",
            "generated_at": _utc_now_iso(),
            "sources": sorted({*(item.get("source_id", "internal_seed") for item in stations), *(item.get("source_id", "internal_seed") for item in airports)}),
        },
        "stations": stations,
        "airports": airports,
    }


def normalize_transport_node_item(item: dict, node_type: str | None = None) -> dict:
    inferred_type = node_type or _item_node_type(item)
    latitude = item.get("latitude")
    longitude = item.get("longitude")
    has_coordinates = latitude is not None and longitude is not None
    source_id = str(item.get("source_id") or "internal_seed")
    is_seed = source_id in {"internal_seed", "internal_calc"}
    node_id = str(item["node_id"])
    iata_code = str(item["iata_code"]).upper() if item.get("iata_code") else None
    if inferred_type == "AIRPORT" and not iata_code:
        iata_code = CONTROLLED_SEED_AIRPORT_IATA.get(node_id)
    source_name = item.get("source_name")
    if not source_name:
        source_name = "Internal Transport Node Seed" if is_seed else "Unknown Transport Node Source"
    source_version = item.get("source_version")
    if not source_version:
        source_version = "manual" if is_seed else ""
    coordinate_quality = item.get("coordinate_quality")
    if not coordinate_quality:
        coordinate_quality = "MANUAL" if has_coordinates and is_seed else ("PROVIDER" if has_coordinates else "MISSING")
    return {
        "node_id": node_id,
        "node_type": inferred_type,
        "node_name": str(item["node_name"]),
        "city_name": _normalize_city_name(str(item["city_name"])),
        "latitude": float(latitude) if latitude is not None else None,
        "longitude": float(longitude) if longitude is not None else None,
        "hub_rank": int(item.get("hub_rank") or 3),
        "aliases": [str(alias) for alias in item.get("aliases", []) if alias],
        "station_code": str(item["station_code"]) if item.get("station_code") else None,
        "iata_code": iata_code,
        "icao_code": str(item["icao_code"]) if item.get("icao_code") else None,
        "source_id": source_id,
        "source_name": str(source_name),
        "source_version": str(source_version),
        "imported_at": item.get("imported_at"),
        "license_status": str(item.get("license_status") or ("APPROVED" if is_seed else "PENDING_REVIEW")),
        "commercial_allowed": bool(item.get("commercial_allowed", False)),
        "coordinate_quality": str(coordinate_quality),
    }


def _item_node_type(item: dict) -> str:
    explicit = str(item.get("node_type") or "")
    if explicit:
        return explicit
    return "AIRPORT" if "airport" in str(item.get("node_id", "")) or "机场" in str(item.get("node_name", "")) else "RAIL_STATION"


def _dedupe_key(item: dict, node_type: str) -> tuple[str, str, str]:
    city = _normalize_city_name(str(item.get("city_name") or ""))
    station_code = str(item.get("station_code") or "")
    iata_code = str(item.get("iata_code") or "")
    external_code = station_code or iata_code
    if external_code:
        return node_type, city, external_code.upper()
    return node_type, city, _normalize_name(str(item.get("node_name") or ""))


def _station_hub_rank(station_name: str, city_name: str) -> int:
    if station_name == city_name:
        return 1
    if station_name in {f"{city_name}北", f"{city_name}南", f"{city_name}东", f"{city_name}西"}:
        return 2
    return 3


def _airport_hub_rank(airport_type: str, scheduled_service: bool) -> int:
    if airport_type == "large_airport" and scheduled_service:
        return 1
    if airport_type in {"large_airport", "medium_airport"}:
        return 2
    return 3


def _city_from_station_name(station_name: str) -> str:
    for suffix in ("北", "南", "东", "西", "站", "线路所"):
        if station_name.endswith(suffix) and len(station_name) > len(suffix):
            return station_name[: -len(suffix)]
    return station_name


def _normalize_airport_city_name(value: str, aliases: dict[str, str]) -> str:
    city = re.sub(r"\(.*?\)", "", value).strip()
    mapped = aliases.get(_normalize_ascii_key(city))
    return mapped or _normalize_city_name(city)


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


def _normalize_name(value: str) -> str:
    return _normalize_city_name(value).replace("站", "").replace("机场", "").lower()


def _normalize_ascii_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _unique_non_empty(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_existing_catalog(path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [*payload.get("stations", []), *payload.get("airports", [])]
