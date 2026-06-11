from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.schemas import DestinationPresentation, TravelRequest

ASSETS_PATH = Path(__file__).resolve().parents[1] / "data" / "destination_assets.json"

DESTINATION_ALIASES: dict[str, tuple[str, ...]] = {
    "beijing": ("北京", "beijing"),
    "shanghai": ("上海", "shanghai"),
    "qingdao": ("青岛", "qingdao"),
    "guangzhou": ("广州", "guangzhou"),
    "shenzhen": ("深圳", "shenzhen"),
    "chengdu": ("成都", "chengdu"),
    "hangzhou": ("杭州", "hangzhou"),
    "xian": ("西安", "xian", "xi'an"),
}


def _last_destination_key_in_text(text: str) -> str | None:
    normalized = text.lower()
    matches: list[tuple[int, str]] = []
    for destination_key, aliases in DESTINATION_ALIASES.items():
        for alias in aliases:
            index = normalized.rfind(alias.lower())
            if index >= 0:
                matches.append((index, destination_key))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


@lru_cache(maxsize=1)
def load_destination_assets() -> dict[str, dict[str, Any]]:
    with ASSETS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def destination_key_for_request(travel_request: TravelRequest) -> str:
    destination_text = travel_request.destination_text.strip()
    if destination_text:
        return _last_destination_key_in_text(destination_text) or "generic"
    return _last_destination_key_in_text(travel_request.raw_user_input) or "generic"


def resolve_destination_presentation(travel_request: TravelRequest) -> DestinationPresentation:
    assets = load_destination_assets()
    destination_key = destination_key_for_request(travel_request)
    asset = assets.get(destination_key) or assets["generic"]
    return DestinationPresentation(**asset)
