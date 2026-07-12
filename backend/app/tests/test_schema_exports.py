import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.models.schemas import (
    LLMRecommendationOutput,
    RecalculateRequest,
    TravelPlanResponse,
    TravelRequest,
)
from scripts.export_schemas import SCHEMAS


def test_exported_schema_files_are_full_pydantic_artifacts():
    for filename, model in SCHEMAS.items():
        path = ROOT / "schemas" / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = model.model_json_schema(ref_template="#/$defs/{model}")
        expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        expected["x-schema-version"] = "1.17"
        assert payload == expected
        assert payload["x-schema-version"] == "1.17"
        assert payload["title"] == model.model_json_schema()["title"]
        if "$defs" in expected:
            assert "$defs" in payload


def test_travel_request_schema_forbids_unknown_fields():
    payload = json.loads((ROOT / "schemas" / "travel-request.schema.json").read_text(encoding="utf-8"))
    assert payload["additionalProperties"] is False
    assert payload["properties"]["schema_version"]["const"] == "1.17"


def test_p0_02_contract_enums_match_schema_v1_17():
    recalculate = json.loads((ROOT / "schemas" / "recalculate-request.schema.json").read_text(encoding="utf-8"))
    travel_plan = json.loads((ROOT / "schemas" / "travel-plan-response.schema.json").read_text(encoding="utf-8"))
    data_sources = json.loads((ROOT / "schemas" / "data-source-status.schema.json").read_text(encoding="utf-8"))

    assert recalculate["properties"]["change_type"]["enum"] == ["SEAT_TYPE", "CABIN_TYPE", "LOCAL_TRANSFER_MODE"]
    assert recalculate["properties"]["recalculate_scope"]["enum"] == ["PLAN_ONLY", "PLAN_AND_RECOMMENDATION", "FULL_REEVALUATION"]
    assert recalculate["properties"]["application_scope"]["enum"] == ["TARGET_PLAN", "RESULT_SET"]
    assert recalculate["$defs"]["SelectedOption"]["properties"]["option_type"]["enum"] == ["SEAT", "CABIN", "TRANSFER_MODE"]

    plan_defs = travel_plan["$defs"]
    assert plan_defs["PlanLifecycleStatus"]["enum"] == ["GENERATED", "PARTIALLY_VERIFIED", "VERIFIED", "EXPIRED", "INVALIDATED", "BOOKED"]
    assert plan_defs["PlanningStatus"]["enum"] == ["PENDING", "RUNNING", "PARTIAL", "COMPLETE", "NO_MATCH", "FAILED"]
    assert plan_defs["SourceFailureClass"]["enum"] == [
        "AUXILIARY_DATA_FAILURE",
        "FALLBACK_AVAILABLE_FAILURE",
        "CORE_FACT_FAILURE",
        "SAFETY_CRITICAL_FAILURE",
    ]
    assert plan_defs["SourceFailureHandlingStrategy"]["enum"] == [
        "RETRY",
        "FALLBACK",
        "PARTIAL_RESULT",
        "DEGRADE_CONFIDENCE",
        "BLOCK_PLAN",
        "EXPLAIN_ONLY",
        "LOG_ONLY",
    ]
    assert plan_defs["TransportMode"]["enum"] == [
        "RAIL",
        "FLIGHT",
        "TAXI",
        "RIDE_HAILING",
        "SUBWAY",
        "BUS",
        "WALK",
        "AIRPORT_TRANSFER",
        "RAIL_STATION_TRANSFER",
        "MIXED",
    ]
    assert plan_defs["PlanType"]["enum"] == [
        "DIRECT_RAIL",
        "TRANSFER_RAIL",
        "MULTI_TRANSFER_RAIL",
        "RAIL_TICKET_ENHANCEMENT",
        "DIRECT_FLIGHT",
        "TRANSFER_FLIGHT",
        "MULTI_AIRPORT_FLIGHT",
        "FLIGHT_RAIL_MIXED",
        "GROUND_ONLY",
        "MIXED",
    ]
    assert "health_status" in data_sources["$defs"]["DataSourceRuntimeStatus"]["required"]
    assert "status" not in data_sources["$defs"]["DataSourceRuntimeStatus"]["properties"]
