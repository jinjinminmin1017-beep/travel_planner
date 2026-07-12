from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models.schemas import (
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
    LLMRecommendationInput,
    LLMRecommendationOutput,
    ParseTravelRequestResponse,
    RecalculateRequest,
    RecalculateResponse,
    TravelPlanResponse,
    TravelRequest,
)

SCHEMA_DIR = ROOT / "schemas"

SCHEMAS = {
    "travel-request.schema.json": TravelRequest,
    "parse-travel-request-response.schema.json": ParseTravelRequestResponse,
    "travel-plan-response.schema.json": TravelPlanResponse,
    "get-travel-plan-response.schema.json": GetTravelPlanResponse,
    "llm-recommendation-input.schema.json": LLMRecommendationInput,
    "llm-recommendation-output.schema.json": LLMRecommendationOutput,
    "recalculate-request.schema.json": RecalculateRequest,
    "recalculate-response.schema.json": RecalculateResponse,
    "booking-redirect-request.schema.json": BookingRedirectRequest,
    "booking-redirect-response.schema.json": BookingRedirectResponse,
    "feedback-request.schema.json": FeedbackRequest,
    "feedback-response.schema.json": FeedbackResponse,
    "app-event-request.schema.json": AppEventRequest,
    "app-event-response.schema.json": AppEventResponse,
    "error-response.schema.json": ErrorResponse,
    "data-source-status.schema.json": DataSourceStatusResponse,
    "health-response.schema.json": HealthResponse,
}


def main() -> None:
    SCHEMA_DIR.mkdir(exist_ok=True)
    common = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AI Travel Planner Common Definitions V1.17",
        "description": "Common definitions are embedded in each exported Pydantic schema for this stage.",
        "type": "object",
        "additionalProperties": True,
    }
    (SCHEMA_DIR / "common.definitions.schema.json").write_text(json.dumps(common, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for filename, model in SCHEMAS.items():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-schema-version"] = "1.17"
        (SCHEMA_DIR / filename).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
