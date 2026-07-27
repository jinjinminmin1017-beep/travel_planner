from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_sources.config_loader import (  # noqa: E402
    load_flight_evidence_config,
    load_project_env,
)
from app.data_sources.flight_evidence_store import FlightEvidenceStore  # noqa: E402

logger = logging.getLogger("flight.exchange.export")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export or clean complete redacted flight-provider exchanges."
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--exchange-id", help="Exchange identifier to export.")
    operation.add_argument(
        "--cleanup-expired",
        action="store_true",
        help="Delete one configured batch of expired exchanges.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_project_env()
    store = FlightEvidenceStore(load_flight_evidence_config())
    if args.cleanup_expired:
        deleted = store.cleanup_expired(batch_size=max(1, args.batch_size))
        logger.info("flight_exchange_cleanup_audit deleted_count=%s", deleted)
        print(json.dumps({"deleted_count": deleted}, ensure_ascii=False))
        return 0
    evidence = store.export_exchange(args.exchange_id)
    logger.info("flight_exchange_export_audit exchange_id=%s", args.exchange_id)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
