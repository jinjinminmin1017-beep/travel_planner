from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.models.schemas import FeedbackResponse, TravelPlan, TravelPlanResponse

DEFAULT_DB_PATH = Path("logs/travel_planner.sqlite3")


def _backend() -> str:
    return os.getenv("TRAVEL_PERSISTENCE_BACKEND", "sqlite").lower()


def _sqlite_path() -> Path:
    return Path(os.getenv("TRAVEL_SQLITE_PATH", str(DEFAULT_DB_PATH)))


def init_persistence() -> None:
    if _backend() == "disabled":
        return
    if _backend() == "postgres":
        _require_optional_module("psycopg", "PostgreSQL persistence requires psycopg in the runtime image.")
        return
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS travel_responses (
              request_id TEXT PRIMARY KEY,
              trace_id TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              response_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS travel_plans (
              plan_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              plan_json TEXT NOT NULL,
              response_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
              feedback_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              trace_id TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              plan_id TEXT NOT NULL,
              source_id TEXT,
              category TEXT NOT NULL,
              feedback_json TEXT NOT NULL,
              received_at TEXT NOT NULL
            )
            """
        )


def save_travel_response(response: TravelPlanResponse) -> None:
    if _backend() == "disabled":
        return
    if _backend() == "postgres":
        return
    init_persistence()
    response_json = response.model_dump_json()
    created_at = response.generated_at.datetime.isoformat()
    with sqlite3.connect(_sqlite_path()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO travel_responses(request_id, trace_id, correlation_id, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (response.request_id, response.trace_id, response.correlation_id, response_json, created_at),
        )
        for plan in response.plans:
            conn.execute(
                "INSERT OR REPLACE INTO travel_plans(plan_id, request_id, plan_json, response_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                (plan.plan_id, response.request_id, plan.model_dump_json(), response_json, created_at),
            )


def save_plan_snapshot(plan: TravelPlan) -> None:
    if _backend() in {"disabled", "postgres"}:
        return
    init_persistence()
    with sqlite3.connect(_sqlite_path()) as conn:
        existing = conn.execute("SELECT request_id, response_json FROM travel_plans WHERE plan_id = ?", (plan.plan_id,)).fetchone()
        if not existing:
            return
        conn.execute(
            "UPDATE travel_plans SET plan_json = ?, updated_at = datetime('now') WHERE plan_id = ?",
            (plan.model_dump_json(), plan.plan_id),
        )


def load_plan_snapshot(plan_id: str) -> TravelPlan | None:
    row = _fetch_one("SELECT plan_json FROM travel_plans WHERE plan_id = ?", (plan_id,))
    if not row:
        return None
    return TravelPlan.model_validate_json(row[0])


def load_response_for_plan_snapshot(plan_id: str) -> TravelPlanResponse | None:
    row = _fetch_one("SELECT response_json FROM travel_plans WHERE plan_id = ?", (plan_id,))
    if not row:
        return None
    return TravelPlanResponse.model_validate_json(row[0])


def save_feedback_snapshot(response: FeedbackResponse) -> None:
    if _backend() in {"disabled", "postgres"}:
        return
    init_persistence()
    with sqlite3.connect(_sqlite_path()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO feedback(feedback_id, request_id, trace_id, correlation_id, plan_id, source_id, category, feedback_json, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                response.feedback_id,
                response.request_id,
                response.trace_id,
                response.correlation_id,
                response.plan_id,
                response.source_id,
                response.category,
                response.model_dump_json(),
                response.received_at.datetime.isoformat(),
            ),
        )


def _fetch_one(query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    if _backend() in {"disabled", "postgres"}:
        return None
    init_persistence()
    with sqlite3.connect(_sqlite_path()) as conn:
        return conn.execute(query, params).fetchone()


def _require_optional_module(name: str, message: str) -> None:
    try:
        __import__(name)
    except ImportError as exc:
        raise RuntimeError(message) from exc
