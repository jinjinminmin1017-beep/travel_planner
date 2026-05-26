import json
from pathlib import Path

from app.models.schemas import (
    LLMRecommendationOutput,
    RecalculateRequest,
    TravelPlanResponse,
    TravelRequest,
)

ROOT = Path(__file__).resolve().parents[3]


def test_exported_schema_files_are_full_pydantic_artifacts():
    expected = {
        "travel-request.schema.json": TravelRequest,
        "travel-plan-response.schema.json": TravelPlanResponse,
        "llm-recommendation-output.schema.json": LLMRecommendationOutput,
        "recalculate-request.schema.json": RecalculateRequest,
    }
    for filename, model in expected.items():
        path = ROOT / "schemas" / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["x-schema-version"] == "1.15"
        assert payload["title"] == model.model_json_schema()["title"]
        assert "$defs" in payload


def test_travel_request_schema_forbids_unknown_fields():
    payload = json.loads((ROOT / "schemas" / "travel-request.schema.json").read_text(encoding="utf-8"))
    assert payload["additionalProperties"] is False
    assert payload["properties"]["schema_version"]["const"] == "1.15"
