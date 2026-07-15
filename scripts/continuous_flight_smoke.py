from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data_sources.config_loader import load_project_env, runtime_statuses  # noqa: E402
from app.data_sources.flight_provider_contracts import AIRLINE_PUBLIC_QUERY_CONTRACTS  # noqa: E402
from app.data_sources.flight_providers import (  # noqa: E402
    FlightSearchRequest,
    search_flight_offers_with_enabled_provider_result,
)


def gate_smoke() -> tuple[bool, dict[str, object]]:
    statuses = {item.source_id: item for item in runtime_statuses()}
    source_results: dict[str, object] = {}
    passed = True
    for source_id, contract in AIRLINE_PUBLIC_QUERY_CONTRACTS.items():
        status = statuses[source_id]
        source_passed = status.health_status != "OK" and contract.blocking_reason is not None
        passed = passed and source_passed
        source_results[source_id] = {
            "passed": source_passed,
            "runtime_status": status.health_status,
            "license_status": status.license_status,
            "contract_version": contract.contract_version,
            "contract_blocking_reason": contract.blocking_reason,
        }
    return passed, source_results


def live_smoke(args: argparse.Namespace) -> tuple[bool, dict[str, object]]:
    result = search_flight_offers_with_enabled_provider_result(
        FlightSearchRequest(
            origin_iata=args.origin,
            destination_iata=args.destination,
            departure_date=date.fromisoformat(args.departure_date),
            adults=args.adults,
            currency_code=args.currency,
            max_results=args.max_results,
            non_stop=True,
        )
    )
    return bool(result.offers), {
        "attempted_source_ids": result.attempted_source_ids,
        "offer_count": len(result.offers),
        "failure_message": result.failure_message,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeated flight-provider safety-gate or live smoke check.")
    parser.add_argument("--mode", choices=("gate", "live"), default="gate")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--origin", default="SHA")
    parser.add_argument("--destination", default="TAO")
    parser.add_argument("--departure-date", default=(date.today() + timedelta(days=30)).isoformat())
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--currency", default="CNY")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 1 or args.interval_seconds < 0:
        parser.error("iterations must be >= 1 and interval-seconds must be >= 0")

    load_project_env()
    all_passed = True
    for index in range(1, args.iterations + 1):
        passed, details = gate_smoke() if args.mode == "gate" else live_smoke(args)
        all_passed = all_passed and passed
        print(json.dumps({"iteration": index, "mode": args.mode, "passed": passed, "details": details}, ensure_ascii=False))
        if not passed and args.stop_on_failure:
            break
        if index < args.iterations and args.interval_seconds:
            time.sleep(args.interval_seconds)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
