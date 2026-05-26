from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str


def new_context(request: Request | None = None) -> RequestContext:
    request_id = request.headers.get("x-request-id") if request else None
    trace_id = request.headers.get("x-trace-id") if request else None
    correlation_id = request.headers.get("x-correlation-id") if request else None
    idempotency_key = request.headers.get("x-idempotency-key") if request else None
    return RequestContext(
        request_id=request_id or f"req_{uuid4().hex[:12]}",
        trace_id=trace_id or f"trace_{uuid4().hex[:12]}",
        correlation_id=correlation_id or f"corr_{uuid4().hex[:12]}",
        idempotency_key=idempotency_key or f"idem_{uuid4().hex[:12]}",
    )


def get_context(request: Request) -> RequestContext:
    ctx = getattr(request.state, "ctx", None)
    if ctx is None:
        ctx = new_context(request)
        request.state.ctx = ctx
    return ctx
