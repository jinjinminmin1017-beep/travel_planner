from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_sources.transport_catalog_providers import (  # noqa: E402
    OURAIRPORTS_AIRPORTS_URL,
    RAIL_12306_STATION_URL,
    city_pinyin_aliases_from_rail_nodes,
    fetch_text,
    load_existing_catalog,
    merge_transport_nodes,
    parse_12306_station_catalog,
    parse_ourairports_catalog,
)

DEFAULT_OUTPUT = ROOT / "backend" / "app" / "data" / "transport_nodes.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import transport node catalog data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output transport_nodes.json path.")
    parser.add_argument("--rail-12306-url", default=RAIL_12306_STATION_URL, help="12306 station_name.js URL.")
    parser.add_argument("--ourairports-url", default=OURAIRPORTS_AIRPORTS_URL, help="OurAirports airports.csv URL.")
    parser.add_argument("--skip-rail", action="store_true", help="Skip 12306 rail station import.")
    parser.add_argument("--skip-airports", action="store_true", help="Skip OurAirports airport import.")
    parser.add_argument("--no-merge-existing", action="store_true", help="Do not preserve existing catalog entries.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for import downloads only.")
    args = parser.parse_args()

    imported = []
    rail_nodes = []
    if not args.skip_rail:
        rail_payload = fetch_text(args.rail_12306_url, insecure=args.insecure)
        rail_nodes = parse_12306_station_catalog(rail_payload, source_version=args.rail_12306_url)
        imported.extend(rail_nodes)
    if not args.skip_airports:
        airport_payload = fetch_text(args.ourairports_url, insecure=args.insecure)
        imported.extend(
            parse_ourairports_catalog(
                airport_payload,
                source_version=args.ourairports_url,
                city_name_aliases=city_pinyin_aliases_from_rail_nodes(rail_nodes),
            )
        )

    imported_source_ids = {node.source_id for node in imported}
    existing = [] if args.no_merge_existing else [
        item for item in load_existing_catalog(args.output)
        if item.get("source_id", "internal_seed") not in imported_source_ids
    ]
    merged = merge_transport_nodes(existing, imported)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(args.output),
                "stations": len(merged["stations"]),
                "airports": len(merged["airports"]),
                "sources": merged["metadata"]["sources"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
