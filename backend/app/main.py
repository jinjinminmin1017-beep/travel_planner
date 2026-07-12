# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from time import perf_counter
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.context import get_context, new_context
from app.core.logging import configure_logging
from app.core.security import evaluate_request_security
from app.data_sources.config_loader import load_data_source_configs, runtime_statuses
from app.data_sources.redirect_providers import create_booking_redirect
from app.models.schemas import (
    AsyncJob,
    AsyncJobStatus,
    AppEventRequest,
    AppEventResponse,
    BookingRedirectRequest,
    BookingRedirectResponse,
    DataSourceStatusResponse,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    GetTravelPlanResponse,
    HealthResponse,
    ParseTravelRequestBody,
    ParseTravelRequestResponse,
    PlanRequest,
    PlanningStatus,
    RecalculateRequest,
    RecalculateResponse,
    TravelRequest,
    TravelPlanResponse,
    now_timepoint,
)
from app.services.intent_parser import IntentParserError, parse_travel_request_with_validation
from app.services.observability import metrics_snapshot, record_app_event
from app.services.persistence import init_persistence
from app.services.planner import plan_trip, recalculate_plan
from app.services.store import get_async_job_by_idempotency, get_async_job_response, get_plan, get_recalculate_response, replace_response_snapshot, save_async_job_response, save_feedback, save_recalculate_response, save_response

configure_logging()
logger = logging.getLogger("app.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_data_source_configs()
    init_persistence()
    yield


app = FastAPI(title="AI Travel Planner", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):517\d",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_context(request: Request, call_next):
    started_at = perf_counter()
    request.state.ctx = new_context(request)
    decision = evaluate_request_security(request)
    request.state.device_id = decision.device_id
    if not decision.allowed:
        duration_ms = (perf_counter() - started_at) * 1000
        logger.warning(
            "http_request_blocked method=%s path=%s status_code=%s duration_ms=%.1f request_id=%s trace_id=%s correlation_id=%s device_id=%s error_code=%s",
            request.method,
            request.url.path,
            decision.status_code,
            duration_ms,
            request.state.ctx.request_id,
            request.state.ctx.trace_id,
            request.state.ctx.correlation_id,
            decision.device_id,
            decision.error_code or "REQUEST_BLOCKED",
        )
        return error_payload(
            request,
            decision.error_code or "REQUEST_BLOCKED",
            decision.user_message or "request blocked",
            decision.user_message or "请求被安全策略拦截。",
            decision.status_code,
            retryable=decision.status_code == 429,
        )
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000
        logger.exception(
            "http_request_error method=%s path=%s duration_ms=%.1f request_id=%s trace_id=%s correlation_id=%s device_id=%s",
            request.method,
            request.url.path,
            duration_ms,
            request.state.ctx.request_id,
            request.state.ctx.trace_id,
            request.state.ctx.correlation_id,
            decision.device_id,
        )
        raise
    response.headers["x-request-id"] = request.state.ctx.request_id
    response.headers["x-trace-id"] = request.state.ctx.trace_id
    response.headers["x-correlation-id"] = request.state.ctx.correlation_id
    response.headers["x-device-id"] = decision.device_id
    duration_ms = (perf_counter() - started_at) * 1000
    logger.info(
        "http_request method=%s path=%s status_code=%s duration_ms=%.1f request_id=%s trace_id=%s correlation_id=%s device_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request.state.ctx.request_id,
        request.state.ctx.trace_id,
        request.state.ctx.correlation_id,
        decision.device_id,
    )
    return response


def error_payload(
    request: Request,
    code: str,
    message: str,
    user_message: str,
    status_code: int,
    details=None,
    retryable: bool = False,
) -> JSONResponse:
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
        details={"errors": jsonable_encoder(exc.errors())},
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


@app.get("/api/admin/data-sources", response_model=DataSourceStatusResponse)
def admin_data_sources_status(request: Request) -> DataSourceStatusResponse:
    return data_sources_status(request)


@app.get("/api/observability/metrics")
def observability_metrics():
    return metrics_snapshot()


@app.post("/api/travel/parse", response_model=ParseTravelRequestResponse)
def parse_travel(body: ParseTravelRequestBody, request: Request):
    ctx = get_context(request)
    try:
        result = parse_travel_request_with_validation(body.raw_user_input, ctx)
    except IntentParserError as exc:
        return _intent_parser_error_response(request, exc)
    return ParseTravelRequestResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        travel_request=result.travel_request,
        llm_validation_result=result.llm_validation_result,
        generated_at=now_timepoint(),
    )


@app.post("/api/travel/plan", response_model=TravelPlanResponse)
def plan_travel(body: PlanRequest, request: Request) -> TravelPlanResponse:
    ctx = get_context(request)
    try:
        response = plan_trip(body.travel_request or body.raw_user_input or "", ctx)
    except IntentParserError as exc:
        return _intent_parser_error_response(request, exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_response(response)
    return response


@app.post("/api/travel/plan/async", response_model=TravelPlanResponse)
def plan_travel_async(body: PlanRequest, request: Request, background_tasks: BackgroundTasks):
    ctx = get_context(request)
    cached_job = get_async_job_by_idempotency(ctx.idempotency_key)
    if cached_job is not None:
        return cached_job
    try:
        travel_request = body.travel_request or parse_travel_request_with_validation(body.raw_user_input or "", ctx).travel_request
    except IntentParserError as exc:
        return _intent_parser_error_response(request, exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = f"job_{uuid4().hex[:12]}"
    response = _planning_job_response(
        travel_request=travel_request,
        ctx=ctx,
        job_id=job_id,
        job_status=AsyncJobStatus.RUNNING,
        planning_status=PlanningStatus.RUNNING,
        progress=15,
        created_at=None,
    )
    save_async_job_response(response)
    background_tasks.add_task(_complete_plan_job, job_id, travel_request, ctx, response.async_job.created_at)
    return response


@app.get("/api/travel/jobs/{job_id}", response_model=TravelPlanResponse)
def get_planning_job(job_id: str) -> TravelPlanResponse:
    response = get_async_job_response(job_id)
    if response is None:
        raise HTTPException(status_code=404, detail="规划任务不存在或已过期。")
    return response


@app.post("/api/travel/jobs/{job_id}/retry", response_model=TravelPlanResponse)
def retry_planning_job(job_id: str, request: Request, background_tasks: BackgroundTasks) -> TravelPlanResponse:
    current = get_async_job_response(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="规划任务不存在或已过期。")
    ctx = get_context(request)
    new_job_id = f"job_{uuid4().hex[:12]}"
    response = _planning_job_response(
        travel_request=current.travel_request,
        ctx=ctx,
        job_id=new_job_id,
        job_status=AsyncJobStatus.RUNNING,
        planning_status=PlanningStatus.RUNNING,
        progress=15,
        created_at=None,
    )
    save_async_job_response(response)
    background_tasks.add_task(_complete_plan_job, new_job_id, current.travel_request, ctx, response.async_job.created_at)
    return response


@app.post("/api/travel/jobs/{job_id}/cancel", response_model=TravelPlanResponse)
def cancel_planning_job(job_id: str) -> TravelPlanResponse:
    current = get_async_job_response(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="规划任务不存在或已过期。")
    if current.async_job is None:
        return current
    if current.async_job.job_status in {AsyncJobStatus.COMPLETE, AsyncJobStatus.PARTIAL_READY, AsyncJobStatus.FAILED, AsyncJobStatus.CANCELLED}:
        return current
    cancelled_job = AsyncJob(
        job_id=job_id,
        job_status=AsyncJobStatus.CANCELLED,
        created_at=current.async_job.created_at,
        updated_at=now_timepoint(),
        polling_url=current.async_job.polling_url,
    )
    cancelled = current.model_copy(
        update={
            "planning_status": PlanningStatus.FAILED,
            "progress": 100,
            "async_job": cancelled_job,
            "user_visible_warnings": [*current.user_visible_warnings, "规划任务已取消。"],
            "generated_at": now_timepoint(),
        }
    )
    save_async_job_response(cancelled)
    return cancelled


def _planning_job_response(
    travel_request: TravelRequest,
    ctx,
    job_id: str,
    job_status: AsyncJobStatus,
    planning_status: PlanningStatus,
    progress: int,
    created_at,
) -> TravelPlanResponse:
    now = now_timepoint()
    job = AsyncJob(
        job_id=job_id,
        job_status=job_status,
        created_at=created_at or now,
        updated_at=now,
        polling_url=f"/api/travel/jobs/{job_id}",
    )
    return TravelPlanResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=ctx.idempotency_key,
        planning_status=planning_status,
        progress=progress,
        travel_request=travel_request,
        destination_presentation=None,
        plans=[],
        recommendation_result=None,
        source_failures=[],
        missing_components=[],
        blocked_plan_types=[],
        missing_plan_explanations=[],
        user_visible_warnings=["规划任务已启动，可继续停留在结果页等待更新。"],
        async_job=job,
        generated_at=now,
    )


def _complete_plan_job(job_id: str, travel_request: TravelRequest, ctx, created_at) -> None:
    current = get_async_job_response(job_id)
    if current and current.async_job and current.async_job.job_status == AsyncJobStatus.CANCELLED:
        return
    waiting = _planning_job_response(
        travel_request=travel_request,
        ctx=ctx,
        job_id=job_id,
        job_status=AsyncJobStatus.WAITING_SOURCE,
        planning_status=PlanningStatus.RUNNING,
        progress=55,
        created_at=created_at,
    )
    save_async_job_response(waiting)
    current = get_async_job_response(job_id)
    if current and current.async_job and current.async_job.job_status == AsyncJobStatus.CANCELLED:
        return
    try:
        final = plan_trip(travel_request, ctx)
        if final.planning_status in {PlanningStatus.COMPLETE, PlanningStatus.NO_MATCH}:
            job_status = AsyncJobStatus.COMPLETE
        elif final.planning_status == PlanningStatus.FAILED:
            job_status = AsyncJobStatus.FAILED
        else:
            job_status = AsyncJobStatus.PARTIAL_READY
        final_job = AsyncJob(
            job_id=job_id,
            job_status=job_status,
            created_at=created_at,
            updated_at=now_timepoint(),
            polling_url=f"/api/travel/jobs/{job_id}",
        )
        save_async_job_response(final.model_copy(update={"async_job": final_job}))
    except Exception:  # Background errors must become pollable business state.
        logger.exception(
            "planning_job_error job_id=%s request_id=%s trace_id=%s correlation_id=%s",
            job_id,
            ctx.request_id,
            ctx.trace_id,
            ctx.correlation_id,
        )
        failed = _planning_job_response(
            travel_request=travel_request,
            ctx=ctx,
            job_id=job_id,
            job_status=AsyncJobStatus.FAILED,
            planning_status=PlanningStatus.FAILED,
            progress=100,
            created_at=created_at,
        )
        failed.missing_components.append("travel_plan")
        failed.user_visible_warnings = ["规划任务暂时失败，请稍后重试。"]
        save_async_job_response(failed)


def _intent_parser_error_response(request: Request, exc: IntentParserError) -> JSONResponse:
    questions = exc.follow_up_questions or ["请补充更明确的日期、地点或交通方式限制。"]
    user_message = f"{exc} {' '.join(questions)}"
    details = {
        "missing_fields": exc.missing_fields,
        "follow_up_questions": questions,
        "llm_validation_result": exc.llm_validation_result.model_dump(mode="json") if exc.llm_validation_result else None,
    }
    return error_payload(
        request,
        "PARSE_NEEDS_INPUT",
        str(exc),
        user_message,
        400,
        details=details,
        retryable=False,
    )


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
    cached = get_recalculate_response(body.plan_id, body.idempotency_key)
    if cached is not None:
        return cached
    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在，无法重算。")
    try:
        response = recalculate_plan(plan, body, ctx)
        if response.updated_response is not None:
            replace_response_snapshot(response.updated_response)
        save_recalculate_response(response)
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/redirect/booking", response_model=BookingRedirectResponse)
def booking_redirect(body: BookingRedirectRequest, request: Request) -> BookingRedirectResponse:
    ctx = get_context(request)
    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在，无法生成跳转。")
    redirect = create_booking_redirect(body, plan)
    return BookingRedirectResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        correlation_id=ctx.correlation_id,
        idempotency_key=body.idempotency_key,
        redirect=redirect,
        generated_at=now_timepoint(),
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
def submit_feedback(body: FeedbackRequest) -> FeedbackResponse:
    sensitive_terms = ("password", "passwd", "cookie", "token", "支付", "密码", "身份证", "账号", "银行卡")
    if body.message and any(term in body.message.lower() for term in sensitive_terms):
        raise HTTPException(status_code=400, detail="反馈内容不能包含第三方账号、支付、实名或凭证信息。")
    response = FeedbackResponse(
        feedback_id=f"fb_{uuid4().hex[:12]}",
        request_id=body.request_id,
        trace_id=body.trace_id,
        correlation_id=body.correlation_id,
        plan_id=body.plan_id,
        source_id=body.source_id,
        category=body.category,
        category_count=0,
        received_at=now_timepoint(),
    )
    return save_feedback(response)


@app.post("/api/events", response_model=AppEventResponse)
def submit_app_event(body: AppEventRequest) -> AppEventResponse:
    forbidden = ("password", "passwd", "account", "cookie", "token", "payment", "real_name", "支付", "密码", "身份证", "银行卡", "账号", "实名")
    metadata_text = str(body.metadata).lower()
    if any(term in metadata_text for term in forbidden):
        raise HTTPException(status_code=400, detail="事件 metadata 不能包含账号、支付、实名或凭证信息。")
    record_app_event(body.event_type, request_id=body.request_id, trace_id=body.trace_id, plan_id=body.plan_id, metadata=body.metadata)
    return AppEventResponse(event_id=f"evt_{uuid4().hex[:12]}", event_type=body.event_type, accepted=True, received_at=now_timepoint())
