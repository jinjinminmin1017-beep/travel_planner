from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

def _read_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _migrated_values(old: dict[str, str]) -> dict[str, str]:
    migrated = dict(old)
    aliases: dict[str, tuple[str, ...]] = {
        "AMAP_WEB_SERVICE_KEY": (
            "TRAVEL_SOURCE_AMAP_ROUTE_API_KEY",
            "TRAVEL_SOURCE_AMAP_GEOCODE_API_KEY",
            "TRAVEL_SOURCE_AMAP_PLACE_SEARCH_API_KEY",
        ),
        "AMAP_API_KEY": (
            "TRAVEL_SOURCE_AMAP_ROUTE_API_KEY",
            "TRAVEL_SOURCE_AMAP_GEOCODE_API_KEY",
            "TRAVEL_SOURCE_AMAP_PLACE_SEARCH_API_KEY",
        ),
        "AMAP_GEOCODING_BASE_URL": (
            "TRAVEL_SOURCE_AMAP_GEOCODE_BASE_URL",
            "TRAVEL_SOURCE_AMAP_PLACE_SEARCH_BASE_URL",
        ),
        "BAIDU_MAP_AK": ("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_API_KEY",),
        "BAIDU_MAP_API_KEY": ("TRAVEL_SOURCE_BAIDU_MAP_ROUTE_API_KEY",),
        "OSRM_ROUTE_BASE_URL": ("TRAVEL_SOURCE_OSRM_ROUTE_BASE_URL",),
        "NOMINATIM_BASE_URL": ("TRAVEL_SOURCE_NOMINATIM_GEOCODE_BASE_URL",),
        "NOMINATIM_USER_AGENT": ("TRAVEL_SOURCE_NOMINATIM_GEOCODE_USER_AGENT",),
        "OPENSKY_BASE_URL": ("TRAVEL_SOURCE_OPENSKY_STATES_BASE_URL",),
        "OPEN_METEO_BASE_URL": ("TRAVEL_SOURCE_OPEN_METEO_FORECAST_BASE_URL",),
        "OPENAI_API_KEY": ("TRAVEL_SOURCE_REAL_LLM_API_KEY",),
        "LLM_API_KEY": ("TRAVEL_SOURCE_REAL_LLM_API_KEY",),
        "REAL_LLM_MODEL": ("TRAVEL_SOURCE_REAL_LLM_MODEL",),
        "REAL_LLM_BASE_URL": ("TRAVEL_SOURCE_REAL_LLM_BASE_URL",),
        "REAL_LLM_TIMEOUT_SECONDS": ("TRAVEL_SOURCE_REAL_LLM_TIMEOUT_SECONDS",),
        "REAL_LLM_MAX_TOKENS": ("TRAVEL_SOURCE_REAL_LLM_MAX_TOKENS",),
        "REAL_LLM_THINKING_DISABLED": ("TRAVEL_SOURCE_REAL_LLM_THINKING_DISABLED",),
    }
    for old_key, new_keys in aliases.items():
        value = old.get(old_key)
        if value is None:
            continue
        for new_key in new_keys:
            if not migrated.get(new_key):
                migrated[new_key] = value

    for key, value in list(migrated.items()):
        if not key.startswith("TRAVEL_SOURCE_") or not key.endswith("_ENABLED") or value.lower() != "true":
            continue
        qps_key = f"{key[:-len('_ENABLED')]}_QPS_LIMIT"
        try:
            qps_limit = int(migrated.get(qps_key, "0"))
        except ValueError:
            qps_limit = 0
        if qps_limit <= 0:
            migrated[qps_key] = "1"
    for key, value in list(migrated.items()):
        if not key.startswith("TRAVEL_SOURCE_") or not key.endswith("_BASE_URL") or not value:
            continue
        hostname = urlparse(value).hostname
        if hostname:
            migrated[f"{key[:-len('_BASE_URL')]}_ALLOWED_HOSTS"] = hostname
    return migrated


def migrate() -> tuple[int, int]:
    old = _read_values(ENV_PATH)
    migrated = _migrated_values(old)
    output: list[str] = []
    retained = 0
    for raw_line in EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue
        key, default = raw_line.split("=", 1)
        is_structural_key = key == "TRAVEL_DATA_SOURCE_IDS" or key.endswith("_ADAPTER")
        value = default if is_structural_key else migrated.get(key, default)
        retained += int(key in migrated and value != default)
        output.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")
    return len(old), retained


if __name__ == "__main__":
    old_count, retained_count = migrate()
    print(f"migrated .env structure: old_keys={old_count}, retained_non_default_values={retained_count}")
