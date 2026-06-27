from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Protocol

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

    def parse_intent(self, raw_user_input: str, request_id: str, current_date: date, default_timezone: str) -> str:
        user_prompt = "\n".join(
            [
                "请将以下用户出行需求解析为 TravelRequest JSON。",
                "",
                "schema_version: 1.15",
                f"request_id: {request_id}",
                f"default_timezone: {default_timezone}",
                f"current_date: {current_date.isoformat()}",
                "",
                "用户输入：",
                raw_user_input,
                "",
                "输出要求：",
                "- 只输出 JSON",
                "- 不要 Markdown",
                "- 不要解释",
                "- 不要生成车次、航班、价格、余票或路线方案",
                "- 必须符合 TravelRequest Schema V1.15",
            ]
        )
        return self._complete_json(_prompt("intent_parser_prompt_v1_0.txt"), user_prompt)

    def repair_intent(self, raw_llm_output: str, invalid_reasons: list[str], raw_user_input: str, request_id: str) -> str:
        user_prompt = "\n".join(
            [
                "你的上一次 Intent Parser 输出非法。",
                "",
                "错误原因：",
                "\n".join(f"- {reason}" for reason in invalid_reasons),
                "",
                "request_id:",
                request_id,
                "",
                "用户原始输入：",
                raw_user_input,
                "",
                "原始 LLM 输出：",
                raw_llm_output,
                "",
                "请重新输出符合 TravelRequest Schema V1.15 的 JSON。",
            ]
        )
        return self._complete_json(_prompt("repair_prompt_v1_0.txt"), user_prompt)

    def recommend(self, llm_input: LLMRecommendationInput) -> LLMRecommendationOutput:
        content = self._complete_json(
            _prompt("recommendation_prompt_v1_0.txt"),
            llm_input.model_dump_json(),
        )
        return LLMRecommendationOutput.model_validate_json(content)

    def repair_recommendation(self, llm_input: LLMRecommendationInput, invalid_reasons: list[str]) -> LLMRecommendationOutput:
        user_prompt = "\n".join(
            [
                "你的上一次 Recommendation 输出非法。",
                "",
                "错误原因：",
                "\n".join(f"- {reason}" for reason in invalid_reasons),
                "",
                "合法 candidate_plan_ids：",
                ", ".join(llm_input.candidate_plan_ids),
                "",
                "原始 LLMRecommendationInput：",
                llm_input.model_dump_json(),
                "",
                "请重新输出符合 LLMRecommendationOutput Schema V1.15 的 JSON。",
                "",
                "唯一允许的顶层字段：schema_version, selected_recommendations, validation_blockers, explanation。",
                "禁止输出顶层字段：request_id, recommendations, candidate_plan_ids, candidate_plans。",
                "selected_recommendations 必须正好包含 CHEAPEST、MOST_COMFORTABLE、BALANCED 三个 slot。",
                "",
                "JSON 模板：",
                '{"schema_version":"1.15","selected_recommendations":[{"schema_version":"1.15","recommendation_type":"CHEAPEST","status":"AVAILABLE","plan_id":"必须来自合法 candidate_plan_ids","reason":"简短原因"},{"schema_version":"1.15","recommendation_type":"MOST_COMFORTABLE","status":"AVAILABLE","plan_id":"必须来自合法 candidate_plan_ids","reason":"简短原因"},{"schema_version":"1.15","recommendation_type":"BALANCED","status":"AVAILABLE","plan_id":"必须来自合法 candidate_plan_ids","reason":"简短原因"}],"validation_blockers":[],"explanation":"一句话总结推荐取舍"}',
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
