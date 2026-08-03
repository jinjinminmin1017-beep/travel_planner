from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.data_sources.config_loader import load_project_env  # noqa: E402
from app.data_sources.flyai_cli_client import FlyAIClient, FlyAIClientError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify FlyAI flight and rail commands complete with strict exit gates.")
    parser.add_argument("--executable", default="")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today() + timedelta(days=7))
    args = parser.parse_args()

    load_project_env(ROOT / ".env")
    api_key = os.getenv("TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY", "").strip()
    executable = args.executable.strip() or os.getenv("TRAVEL_SOURCE_FLIGGY_FLYAI_EXECUTABLE", "").strip()
    if not api_key:
        print(json.dumps({"status": "BLOCKED", "error_code": "FLIGGY_API_KEY_MISSING"}))
        return 2
    if not executable:
        print(json.dumps({"status": "BLOCKED", "error_code": "FLIGGY_EXECUTABLE_MISSING"}))
        return 2

    client = FlyAIClient(api_key=api_key, executable=executable, timeout_seconds=args.timeout_seconds)
    checks: dict[str, dict[str, int]] = {}
    try:
        flight = client.search_flight(
            origin="上海",
            destination="北京",
            departure_date=args.date,
            non_stop=True,
        )
        checks["flight"] = {"item_count": flight.item_count, "elapsed_ms": flight.elapsed_ms}
        train = client.search_train(
            origin="上海虹桥",
            destination="北京南",
            departure_date=args.date,
        )
        checks["rail"] = {"item_count": train.item_count, "elapsed_ms": train.elapsed_ms}
    except FlyAIClientError as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code, "failure_kind": exc.failure_kind}))
        return 2

    print(json.dumps({"status": "READY", "checks": checks}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
