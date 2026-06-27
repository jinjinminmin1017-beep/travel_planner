from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Request

DEFAULT_BODY_LIMIT_BYTES = 64 * 1024
DEFAULT_RATE_LIMIT_PER_MINUTE = 60

_RATE_WINDOWS: dict[str, tuple[datetime, int]] = {}


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    device_id: str
    error_code: str | None = None
    user_message: str | None = None
    status_code: int = 200


def evaluate_request_security(request: Request) -> SecurityDecision:
    device_id = request.headers.get("x-device-id") or f"anon_{uuid4().hex[:12]}"
    api_key_required = os.getenv("TRAVEL_REQUIRE_API_KEY", "false").lower() == "true"
    expected_api_key = os.getenv("TRAVEL_API_KEY", "")
    if api_key_required and request.headers.get("x-api-key") != expected_api_key:
        return SecurityDecision(False, device_id, "UNAUTHORIZED", "未授权请求不能使用规划服务。", 401)

    content_length = request.headers.get("content-length")
    max_body_size = int(os.getenv("TRAVEL_MAX_BODY_BYTES", str(DEFAULT_BODY_LIMIT_BYTES)))
    if content_length and int(content_length) > max_body_size:
        return SecurityDecision(False, device_id, "REQUEST_TOO_LARGE", "请求内容过大，请缩短输入后重试。", 413)

    limit = int(os.getenv("TRAVEL_API_RATE_LIMIT_PER_MINUTE", str(DEFAULT_RATE_LIMIT_PER_MINUTE)))
    now = datetime.now(timezone.utc)
    window_start, count = _RATE_WINDOWS.get(device_id, (now, 0))
    if now - window_start >= timedelta(minutes=1):
        window_start, count = now, 0
    count += 1
    _RATE_WINDOWS[device_id] = (window_start, count)
    if count > limit:
        return SecurityDecision(False, device_id, "RATE_LIMITED", "请求过于频繁，请稍后再试。", 429)
    return SecurityDecision(True, device_id)
