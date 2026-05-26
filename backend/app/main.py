from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.context import get_context, new_context
from app.data_sources.config_loader import runtime_statuses
from app.models.schemas import (
    BookingRedirectRequest,
    BookingRedirectResponse,
    DataSourceStatusResponse,
    ErrorResponse,
    GetTravelPlanResponse,
    HealthResponse,
    ParseTravelRequestBody,
    ParseTravelRequestResponse,
    PlanRequest,
    RecalculateRequest,
    RecalculateResponse,
    TravelPlanResponse,
    now_timepoint,
)
from app.services.intent_parser import parse_travel_request
from app.services.planner import _redirect, plan_trip, recalculate_plan
from app.services.store import get_plan, save_response

app = FastAPI(title="AI Travel Planner", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_context(request: Request, call_next):
    request.state.ctx = new_context(request)
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.ctx.request_id
    response.headers["x-trace-id"] = request.state.ctx.trace_id
    response.headers["x-correlation-id"] = request.state.ctx.correlation_id
    return response


def error_payload(request: Request, code: str, message: str, user_message: str, status_code: int, details=None, retryable: bool = False) -> JSONResponse:
    ctx = get_context(request)
    payload = ErrorResponse(
        request_id=ctx.request_id,
        error_code=code,
        message=message,
        user_visible_message=user_message,
        retryable=retryable,
        details=details,
        generated_at=now_timepoint(),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_payload(
        request,
        "VALIDATION_ERROR",
        "Request validation failed",
        "输入结构不符合系统要求，请检查后重试。",
        422,
        details={"errors": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return error_payload(
        request,
        f"HTTP_{exc.status_code}",
        str(exc.detail),
        str(exc.detail),
        exc.status_code,
        details=None,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return error_payload(
        request,
        "INTERNAL_ERROR",
        str(exc),
        "服务暂时无法完成请求，请稍后重试。",
        500,
        details=None,
        retryable=True,
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="OK", service_name="ai-travel-planner-backend", version="0.1.0", checked_at=now_timepoint())


@app.get("/api/data-sources/status", response_model=DataSourceStatusResponse)
def data_sources_status(request: Request) -> DataSourceStatusResponse:
    ctx = get_context(request)
    return DataSourceStatusResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        sources=runtime_statuses(),
        generated_at=now_timepoint(),
    )


@app.post("/api/travel/parse", response_model=ParseTravelRequestResponse)
def parse_travel(body: ParseTravelRequestBody, request: Request) -> ParseTravelRequestResponse:
    ctx = get_context(request)
    try:
        travel_request = parse_travel_request(body.raw_user_input, ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ParseTravelRequestResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        travel_request=travel_request,
        generated_at=now_timepoint(),
    )


@app.post("/api/travel/plan", response_model=TravelPlanResponse)
def plan_travel(body: PlanRequest, request: Request) -> TravelPlanResponse:
    ctx = get_context(request)
    try:
        response = plan_trip(body.travel_request or body.raw_user_input or "", ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_response(response)
    return response


@app.get("/api/travel/plans/{plan_id}", response_model=GetTravelPlanResponse)
def get_travel_plan(plan_id: str, request: Request) -> GetTravelPlanResponse:
    ctx = get_context(request)
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在或已过期。")
    return GetTravelPlanResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        plan=plan,
        generated_at=now_timepoint(),
    )


@app.post("/api/travel/recalculate", response_model=RecalculateResponse)
def recalculate(body: RecalculateRequest, request: Request) -> RecalculateResponse:
    ctx = get_context(request)
    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在，无法重算。")
    try:
        return recalculate_plan(plan, body, ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/redirect/booking", response_model=BookingRedirectResponse)
def booking_redirect(body: BookingRedirectRequest, request: Request) -> BookingRedirectResponse:
    ctx = get_context(request)
    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在，无法生成跳转。")
    redirect = _redirect(body.redirect_type, available=body.redirect_type != "OTA")
    return BookingRedirectResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=body.idempotency_key,
        redirect=redirect,
        generated_at=now_timepoint(),
    )

