from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.models.schemas import now_timepoint

logger = logging.getLogger("app.llm")


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def log_llm_call(**payload: Any) -> None:
    audit_payload = {
        "schema_version": "1.15",
        "created_at": now_timepoint().model_dump(mode="json"),
        **payload,
    }
    logger.info("llm_call %s", json.dumps(audit_payload, ensure_ascii=False, sort_keys=True))
