from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.context import new_context
from app.data_sources.config_loader import load_data_source_configs
from app.services.planner import plan_trip


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Return non-zero when any golden route misses expectations.")
    args = parser.parse_args()
    load_data_source_configs()
    golden_routes = json.loads((ROOT / "docs" / "GOLDEN_ROUTES.json").read_text(encoding="utf-8"))
    results = []
    passed = 0
    for route in golden_routes:
        response = plan_trip(route["raw_user_input"], new_context())
        plan_types = {plan.plan_type for plan in response.plans}
        expected_types = set(route["expected_any_plan_types"])
        status_ok = response.planning_status in set(route["expected_statuses"])
        coverage_ok = not expected_types or bool(plan_types & expected_types)
        ok = status_ok and coverage_ok
        passed += int(ok)
        results.append(
            {
                "route_id": route["route_id"],
                "ok": ok,
                "planning_status": response.planning_status,
                "plan_count": len(response.plans),
                "covered_plan_types": sorted(plan_types),
                "partial": response.planning_status == "PARTIAL",
                "recommendation_available": response.recommendation_result is not None,
            }
        )
    output = {"total": len(golden_routes), "passed": passed, "pass_rate": passed / max(len(golden_routes), 1), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if args.strict and passed != len(golden_routes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
