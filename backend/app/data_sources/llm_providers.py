from __future__ import annotations

import os
from typing import Protocol

import httpx

from app.data_sources.config_loader import has_required_secret, load_data_source_configs
from app.models.schemas import LLMRecommendationInput, LLMRecommendationOutput


class LLMProviderError(RuntimeError):
    pass


class RecommendationLLMProvider(Protocol):
    source_id: str

    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
        ...


class OpenAICompatibleLLMProvider:
    source_id = "real_llm"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=15.0)
        self.base_url = base_url.rstrip("/")

    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
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
                        "content": (
                            "You select exactly three travel recommendation slots from verified candidate_plan_ids. "
                            "Return JSON only with schema_version, selected_recommendations, validation_blockers, explanation. "
                            "Never invent plan ids or modify facts."
                        ),
                    },
                    {
                        "role": "user",
                        "content": llm_input.model_dump_json(),
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
        return LLMRecommendationOutput.model_validate_json(content)


def build_enabled_llm_provider(environment: str | None = None) -> RecommendationLLMProvider | None:
    configs = {config.source_id: config for config in load_data_source_configs(environment)}
    config = configs.get("real_llm")
    if not config or not config.enabled or config.license_status != "APPROVED" or not has_required_secret("real_llm"):
        return None
    api_key = _first_env("OPENAI_API_KEY", "LLM_API_KEY")
    model = os.getenv("REAL_LLM_MODEL", "gpt-4.1-mini")
    base_url = os.getenv("REAL_LLM_BASE_URL", "https://api.openai.com/v1")
    return OpenAICompatibleLLMProvider(api_key=api_key, model=model, base_url=base_url)


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise LLMProviderError(f"missing LLM credential env: {'/'.join(names)}")
