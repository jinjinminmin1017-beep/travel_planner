from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import LLMRecommendationInput, LLMRecommendationOutput

PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"


class LLMProviderError(RuntimeError):
    pass


class IntentParserLLMProvider(Protocol):
    source_id: str
    model_name: str

    def parse_intent(self, raw_user_input: str, request_id: str, current_date: date, default_timezone: str) -> str:
        ...

    def repair_intent(self, raw_llm_output: str, invalid_reasons: list[str], raw_user_input: str, request_id: str) -> str:
        ...


class RecommendationLLMProvider(Protocol):
    source_id: str
    model_name: str

    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
        ...

    def repair_recommendation(self, llm_input: LLMRecommendationInput, invalid_reasons: list[str]) -> LLMRecommendationOutput:
        ...


class OpenAICompatibleLLMProvider:
    source_id = "real_llm"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.model = model
        self.model_name = model
        self.client = client or httpx.Client(timeout=_llm_timeout_seconds())
        self.base_url = base_url.rstrip("/")
        self._last_recommendation_raw_output: str | None = None

    def parse_intent(self, raw_user_input: str, request_id: str, current_date: date, default_timezone: str) -> str:
        user_prompt = "\n".join(
            [
                "Parse the following user travel request into TravelRequest JSON.",
                "",
                "schema_version: 1.15",
                f"request_id: {request_id}",
                f"default_timezone: {default_timezone}",
                f"current_date: {current_date.isoformat()}",
                "",
                "raw_user_input:",
                raw_user_input,
                "",
                "Output requirements:",
                "- Output JSON only.",
                "- Do not output Markdown or explanations.",
                "- Copy request_id and raw_user_input exactly.",
                '- Use schema_version "1.15".',
                "- TimePoint fields must be null or objects with datetime, timezone, and source_timezone.",
                '- Do not output bare time strings such as "08:00" for time_window_start or time_window_end.',
                "- Do not generate trains, flights, fares, ticket inventory, candidate places, routes, transfers, recommendations, booking links, or map links.",
            ]
        )
        return self._complete_json(_prompt("intent_parser_prompt_v1_0.txt"), user_prompt)

    def repair_intent(self, raw_llm_output: str, invalid_reasons: list[str], raw_user_input: str, request_id: str) -> str:
        user_prompt = "\n".join(
            [
                "Repair the previous Intent Parser output.",
                "",
                "target_schema: TravelRequest Schema V1.15",
                "",
                "error_reasons:",
                "\n".join(f"- {reason}" for reason in invalid_reasons),
                "",
                "request_id:",
                request_id,
                "",
                "raw_user_input:",
                raw_user_input,
                "",
                "previous_raw_llm_output:",
                raw_llm_output,
                "",
                "Return repaired JSON only. Copy request_id and raw_user_input exactly. Do not guess missing origin, destination, or travel_date.",
            ]
        )
        return self._complete_json(_prompt("repair_prompt_v1_0.txt"), user_prompt)

    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
        content = self._complete_json(
            _prompt("recommendation_prompt_v1_0.txt"),
            _recommendation_user_prompt(llm_input),
        )
        self._last_recommendation_raw_output = content
        return LLMRecommendationOutput.model_validate_json(content)

    def repair_recommendation(self, llm_input: LLMRecommendationInput, invalid_reasons: list[str]) -> LLMRecommendationOutput:
        previous_raw_output = self._last_recommendation_raw_output or "UNAVAILABLE"
        user_prompt = "\n".join(
            [
                "Repair the previous Recommendation output.",
                "",
                "target_schema: LLMRecommendationOutput Schema V1.15",
                "",
                "error_reasons:",
                "\n".join(f"- {reason}" for reason in invalid_reasons),
                "",
                "previous_raw_llm_output:",
                previous_raw_output,
                "",
                _valid_plan_id_section(llm_input),
                "",
                "LLMRecommendationSelectionInput JSON:",
                json.dumps(_recommendation_selection_payload(llm_input), ensure_ascii=False, separators=(",", ":")),
                "",
                "Return repaired JSON for LLMRecommendationOutput Schema V1.15.",
                "",
                "Allowed top-level fields: schema_version, selected_recommendations, validation_blockers, explanation.",
                "Forbidden top-level fields: request_id, recommendations, candidate_plan_ids, candidate_plans.",
                "selected_recommendations must contain exactly CHEAPEST, MOST_COMFORTABLE, and BALANCED.",
                "If status=AVAILABLE, plan_id must exactly match one ID from the legal plan_id list.",
                "If no candidate is available for a slot, use status=NOT_AVAILABLE and plan_id=null.",
            ]
        )
        content = self._complete_json(_prompt("repair_prompt_v1_0.txt"), user_prompt)
        return LLMRecommendationOutput.model_validate_json(content)

    def _complete_json(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM response has no message content") from exc
        return content


def build_enabled_llm_provider(environment: str | None = None) -> RecommendationLLMProvider | None:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("real_llm")
    if not config or not config.enabled or config.license_status != "APPROVED" or not has_required_secret("real_llm"):
        return None
    api_key = _first_env("OPENAI_API_KEY", "LLM_API_KEY")
    model = os.getenv("REAL_LLM_MODEL", "gpt-4.1-mini")
    base_url = os.getenv("REAL_LLM_BASE_URL", "https://api.openai.com/v1")
    return OpenAICompatibleLLMProvider(api_key=api_key, model=model, base_url=base_url)


def build_enabled_intent_llm_provider(environment: str | None = None) -> IntentParserLLMProvider | None:
    provider = build_enabled_llm_provider(environment)
    return provider if provider and hasattr(provider, "parse_intent") else None


def _valid_plan_id_section(llm_input: LLMRecommendationInput) -> str:
    plan_ids = "\n".join(f"- {plan_id}" for plan_id in llm_input.candidate_plan_ids)
    return "\n".join(
        [
            "Legal plan_id list. AVAILABLE.plan_id may only copy one complete ID from a line below:",
            plan_ids,
        ]
    )


def _recommendation_user_prompt(llm_input: LLMRecommendationInput) -> str:
    selection_payload = _recommendation_selection_payload(llm_input)
    return "\n".join(
        [
            _valid_plan_id_section(llm_input),
            "",
            "Before output, self-check:",
            "- Top-level fields must be only schema_version, selected_recommendations, validation_blockers, explanation.",
            "- selected_recommendations must contain exactly CHEAPEST, MOST_COMFORTABLE, and BALANCED.",
            "- Every AVAILABLE.plan_id must exactly equal one ID from the legal plan_id list.",
            "- Do not output plan_id explanations, template text, field names, or placeholders.",
            "- Do not modify any candidate_plans fact field.",
            "",
            "LLMRecommendationSelectionInput JSON. This is a compact summary for selection only; backend validation owns the full TravelPlan objects:",
            json.dumps(selection_payload, ensure_ascii=False, separators=(",", ":")),
        ]
    )


def _recommendation_selection_payload(llm_input: LLMRecommendationInput) -> dict[str, Any]:
    return {
        "schema_version": llm_input.schema_version,
        "request_id": llm_input.request_id,
        "travel_request": {
            "origin_text": llm_input.travel_request.origin_text,
            "destination_text": llm_input.travel_request.destination_text,
            "travel_date": llm_input.travel_request.travel_date.isoformat(),
            "time_anchor_type": llm_input.travel_request.time_anchor_type,
            "preferences": [_enum_value(preference) for preference in llm_input.travel_request.preferences],
            "preference_source": llm_input.travel_request.preference_source,
            "soft_preferences": llm_input.travel_request.soft_preferences.model_dump(mode="json"),
        },
        "candidate_plan_ids": llm_input.candidate_plan_ids,
        "candidate_plans": [_plan_summary(plan) for plan in llm_input.candidate_plans],
    }


def _plan_summary(plan: Any) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "plan_name": plan.plan_name,
        "plan_type": _enum_value(plan.plan_type),
        "plan_lifecycle_status": _enum_value(plan.plan_lifecycle_status),
        "recommendation_eligibility": _enum_value(plan.recommendation_eligibility),
        "can_be_selected_by_llm": plan.can_be_selected_by_llm,
        "block_reason_code": plan.block_reason_code,
        "block_reason_message": plan.block_reason_message,
        "total_duration_minutes": plan.total_duration_minutes,
        "departure_time": _time_summary(plan.departure_time),
        "arrival_time": _time_summary(plan.arrival_time),
        "total_cost": plan.cost_breakdown.total_cost.model_dump(mode="json"),
        "comfort_score": {
            "total_score": plan.comfort_score.total_score,
            "breakdown": plan.comfort_score.breakdown,
            "confidence": plan.comfort_score.confidence,
        },
        "risk_assessment": {
            "overall_risk_level": _enum_value(plan.risk_assessment.overall_risk_level),
            "recommendation_allowed": plan.risk_assessment.recommendation_allowed,
            "risk_titles": [item.title for item in plan.risk_assessment.risk_items[:3]],
        },
        "data_quality": plan.data_quality.model_dump(mode="json"),
        "ticket_enhancement": _ticket_enhancement_summary(plan.ticket_enhancement),
        "segments": [_segment_summary(segment) for segment in plan.segments],
    }


def _segment_summary(segment: Any) -> dict[str, Any]:
    payload = segment.model_dump(mode="json")
    segment_type = payload.get("segment_type")
    summary: dict[str, Any] = {
        "segment_type": segment_type,
        "duration_minutes": payload.get("duration_minutes"),
        "departure_time": _time_summary(getattr(segment, "departure_time", None)),
        "arrival_time": _time_summary(getattr(segment, "arrival_time", None)),
    }
    if segment_type == "LOCAL_TRANSFER":
        summary.update(
            {
                "origin": payload.get("origin"),
                "destination": payload.get("destination"),
                "transfer_mode": payload.get("transfer_mode"),
                "estimated_cost": payload.get("estimated_cost"),
                "distance_meters": payload.get("distance_meters"),
                "traffic_risk": payload.get("traffic_risk"),
            }
        )
    elif segment_type == "RAIL":
        summary.update(
            {
                "train_number": payload.get("train_number"),
                "origin_station": payload.get("origin_station"),
                "destination_station": payload.get("destination_station"),
                "selected_seat_option_id": payload.get("selected_seat_option_id"),
                "seat_options": [
                    {
                        "seat_type": option.get("seat_type"),
                        "price": option.get("price"),
                        "availability": option.get("availability"),
                    }
                    for option in payload.get("seat_options", [])
                ],
            }
        )
    elif segment_type == "FLIGHT":
        summary.update(
            {
                "flight_number": payload.get("flight_number"),
                "origin_airport": payload.get("origin_airport"),
                "destination_airport": payload.get("destination_airport"),
                "selected_cabin_option_id": payload.get("selected_cabin_option_id"),
                "previous_flight_risk_available": payload.get("previous_flight_risk_available"),
                "cabin_options": [
                    {
                        "cabin_type": option.get("cabin_type"),
                        "price": option.get("price"),
                        "availability": option.get("availability"),
                    }
                    for option in payload.get("cabin_options", [])
                ],
            }
        )
    return summary


def _ticket_enhancement_summary(ticket_enhancement: Any | None) -> dict[str, Any] | None:
    if ticket_enhancement is None:
        return None
    return {
        "grade": _enum_value(ticket_enhancement.grade),
        "risk_level": _enum_value(ticket_enhancement.risk_level),
        "extra_cost": ticket_enhancement.extra_cost.model_dump(mode="json"),
        "recommendation_message": ticket_enhancement.recommendation_message,
    }


def _time_summary(value: Any | None) -> str | None:
    return value.datetime.isoformat() if value is not None else None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise LLMProviderError(f"missing LLM credential env: {'/'.join(names)}")


def _llm_timeout_seconds() -> float:
    raw_value = os.getenv("REAL_LLM_TIMEOUT_SECONDS", "45")
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return 45.0


def _prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8")
