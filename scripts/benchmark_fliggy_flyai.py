from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.data_sources.config_loader import load_project_env  # noqa: E402
from app.data_sources.flight_providers import FlightSearchRequest  # noqa: E402
from app.data_sources.fliggy_flyai_provider import (  # noqa: E402
    FliggyFlyAIProvider,
    _COMMAND_CACHE,
    _IN_FLIGHT,
)
from app.data_sources.flyai_cli_client import FlyAIClient  # noqa: E402
from app.data_sources.rail_providers import RailSearchRequest  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile for an empty sample")
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def _measure(call) -> tuple[float, int]:
    started_at = time.perf_counter()
    offers = call()
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    return round(elapsed_ms, 2), len(offers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 50-sample FlyAI cold/warm latency gate without logging URLs or secrets.")
    parser.add_argument("--samples-per-product", type=int, default=50)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--flight-origin", default="上海")
    parser.add_argument("--flight-destination", default="青岛")
    parser.add_argument("--rail-origin", default="上海")
    parser.add_argument("--rail-destination", default="北京")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.samples_per_product < 50:
        parser.error("--samples-per-product must be at least 50 for the release gate")
    if args.interval_seconds < 1:
        parser.error("--interval-seconds must be at least 1 for the low-frequency release gate")

    load_project_env(ROOT / ".env")
    api_key = os.getenv("TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"status": "BLOCKED", "reason": "TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY is missing"}))
        return 2

    executable = os.getenv("TRAVEL_SOURCE_FLIGGY_FLYAI_EXECUTABLE", "node_modules/.bin/flyai").strip()
    provider = FliggyFlyAIProvider(
        client=FlyAIClient(api_key=api_key, executable=executable, timeout_seconds=args.timeout_seconds),
        qps_limit=1,
        cache_ttl_seconds=60,
        redirect_allowed_hosts=("router.feizhu.com", "fliggy.com"),
    )
    flight_request = FlightSearchRequest(
        origin_iata="",
        destination_iata="",
        origin_city_name=args.flight_origin,
        destination_city_name=args.flight_destination,
        departure_date=args.date,
        max_results=5,
    )
    rail_request = RailSearchRequest(
        train_number="",
        origin_station=args.rail_origin,
        destination_station=args.rail_destination,
        departure_date=args.date,
    )

    cold_ms: list[float] = []
    warm_ms: list[float] = []
    first_card_ms: list[float] = []
    product_counts = {"flight": 0, "rail": 0}
    attempt_counts = {"flight": 0, "rail": 0}
    failure_counts: dict[str, int] = {}
    total_samples = args.samples_per_product * 2
    for index in range(total_samples):
        sample_started_at = time.monotonic()
        _COMMAND_CACHE.clear()
        _IN_FLIGHT.clear()
        product = "flight" if index % 2 == 0 else "rail"
        attempt_counts[product] += 1
        request = flight_request if product == "flight" else rail_request
        try:
            cold, cold_count = _measure(lambda: provider.search_offers(request))
            warm, warm_count = _measure(lambda: provider.search_offers(request))
            if cold_count <= 0 or warm_count <= 0:
                raise RuntimeError("NO_USABLE_EXACT_PRICE_CARD")
            product_counts[product] += 1
            cold_ms.append(cold)
            warm_ms.append(warm)
            first_card_ms.append(cold)
        except Exception as exc:
            error_code = str(exc).split(":", 1)[0].strip() or exc.__class__.__name__
            failure_counts[error_code] = failure_counts.get(error_code, 0) + 1
        remaining_interval = args.interval_seconds - (time.monotonic() - sample_started_at)
        if remaining_interval > 0 and index + 1 < total_samples:
            time.sleep(remaining_interval)

    latency_gate_passed = bool(first_card_ms) and _percentile(first_card_ms, 0.95) <= 3000
    sample_gate_passed = product_counts == {"flight": args.samples_per_product, "rail": args.samples_per_product}

    report = {
        "status": "PASS" if latency_gate_passed and sample_gate_passed else "FAIL",
        "samples_per_product": args.samples_per_product,
        "attempt_counts": attempt_counts,
        "product_counts": product_counts,
        "failure_counts": failure_counts,
        "cold_ms": {
            "p50": round(statistics.median(cold_ms), 2) if cold_ms else None,
            "p95": _percentile(cold_ms, 0.95) if cold_ms else None,
            "p99": _percentile(cold_ms, 0.99) if cold_ms else None,
        },
        "warm_ms": {
            "p50": round(statistics.median(warm_ms), 2) if warm_ms else None,
            "p95": _percentile(warm_ms, 0.95) if warm_ms else None,
            "p99": _percentile(warm_ms, 0.99) if warm_ms else None,
        },
        "first_available_card_target_ms": 3000,
    }
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
