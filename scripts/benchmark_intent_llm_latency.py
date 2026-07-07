from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
PROMPT_DIR = BACKEND_DIR / "app" / "llm" / "prompts"
LOG_DIR = ROOT / "logs"

sys.path.insert(0, str(BACKEND_DIR))

from app.models.schemas import TravelRequest  # noqa: E402
from app.services.intent_parser import validate_travel_request_semantics  # noqa: E402

DEFAULT_RAW_INPUT = "明天从上海东方明珠塔到成都太古里，高铁优先，上午出发"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_REAL_LLM_MAX_TOKENS = 800


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark intent LLM latency without logging secrets or full outputs.")
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--raw-input", default=DEFAULT_RAW_INPUT)
    parser.add_argument("--timeout", type=float, default=None, help="Override request timeout seconds. Defaults to REAL_LLM_TIMEOUT_SECONDS.")
    parser.add_argument("--max-tokens", type=int, default=None, help="Override REAL_LLM_MAX_TOKENS. Defaults to 800.")
    parser.add_argument("--enable-thinking", action="store_true", help="Omit the GLM thinking disabled request field for comparison.")
    parser.add_argument("--no-response-format", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--label", default="baseline")
    return parser.parse_args()


def env_value(*names: str, default: str | None = None) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    if default is not None:
        return default
    raise RuntimeError(f"Missing required environment variable: {'/'.join(names)}")


def env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value >= 1 else default


def prompt_text(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8")


def build_user_prompt(raw_input: str, request_id: str, current_date: date) -> str:
    return "\n".join(
        [
            "请将以下用户出行需求解析为 TravelRequest JSON。",
            "",
            "schema_version: 1.15",
            f"request_id: {request_id}",
            f"default_timezone: {DEFAULT_TIMEZONE}",
            f"current_date: {current_date.isoformat()}",
            "",
            "用户输入：",
            raw_input,
            "",
            "输出要求：",
            "- 只输出 JSON",
            "- 不要 Markdown",
            "- 不要解释",
            "- 不要生成车次、航班、价格、余票或路线方案",
            "- 必须符合 TravelRequest Schema V1.15",
        ]
    )


def build_payload(model: str, system_prompt: str, user_prompt: str, *, response_format: bool, max_tokens: int, thinking_disabled: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if response_format:
        payload["response_format"] = {"type": "json_object"}
    if thinking_disabled:
        payload["thinking"] = {"type": "disabled"}
    return payload


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in records if item["status"] == "success"]
    failures = [item for item in records if item["status"] != "success"]
    all_total_values = [item["total_ms"] for item in records]
    success_total_values = [item["total_ms"] for item in successes]
    return {
        "runs": len(records),
        "success_count": len(successes),
        "failure_count": len(failures),
        "failure_types": sorted({item.get("error_type") for item in failures if item.get("error_type")}),
        "all_total_ms": {
            "avg": round(statistics.mean(all_total_values), 1) if all_total_values else None,
            "median": round(statistics.median(all_total_values), 1) if all_total_values else None,
            "p90": round(percentile(all_total_values, 0.90), 1) if all_total_values else None,
            "p95": round(percentile(all_total_values, 0.95), 1) if all_total_values else None,
            "min": round(min(all_total_values), 1) if all_total_values else None,
            "max": round(max(all_total_values), 1) if all_total_values else None,
        },
        "success_total_ms": {
            "avg": round(statistics.mean(success_total_values), 1) if success_total_values else None,
            "median": round(statistics.median(success_total_values), 1) if success_total_values else None,
            "p90": round(percentile(success_total_values, 0.90), 1) if success_total_values else None,
            "p95": round(percentile(success_total_values, 0.95), 1) if success_total_values else None,
            "min": round(min(success_total_values), 1) if success_total_values else None,
            "max": round(max(success_total_values), 1) if success_total_values else None,
        },
    }


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    api_key = env_value("OPENAI_API_KEY", "LLM_API_KEY")
    model = env_value("REAL_LLM_MODEL", default="gpt-4.1-mini")
    base_url = env_value("REAL_LLM_BASE_URL", default="https://api.openai.com/v1").rstrip("/")
    timeout_seconds = args.timeout if args.timeout is not None else float(env_value("REAL_LLM_TIMEOUT_SECONDS", default="45"))
    max_tokens = args.max_tokens if args.max_tokens is not None and args.max_tokens >= 1 else env_int("REAL_LLM_MAX_TOKENS", DEFAULT_REAL_LLM_MAX_TOKENS)
    thinking_disabled = not args.enable_thinking and os.getenv("REAL_LLM_THINKING_DISABLED", "true").strip().lower() != "false"
    system_prompt = prompt_text("intent_parser_prompt_v1_0.txt")
    response_format = not args.no_response_format
    current_date = date.today()

    started_at = datetime.now().strftime("%Y%m%d-%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = LOG_DIR / f"intent_llm_perf_{started_at}_{args.label}.jsonl"
    summary_path = LOG_DIR / f"intent_llm_perf_{started_at}_{args.label}_summary.json"

    records: list[dict[str, Any]] = []
    timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
    with httpx.Client(timeout=timeout) as client, jsonl_path.open("w", encoding="utf-8") as output:
        for index in range(1, args.runs + 1):
            request_id = f"bench_{uuid4().hex[:12]}"
            user_prompt = build_user_prompt(args.raw_input, request_id, current_date)
            payload = build_payload(model, system_prompt, user_prompt, response_format=response_format, max_tokens=max_tokens, thinking_disabled=thinking_disabled)
            body_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            record: dict[str, Any] = {
                "run": index,
                "label": args.label,
                "model": model,
                "base_url_host": base_url.split("//")[-1].split("/")[0],
                "timeout_seconds": timeout_seconds,
                "response_format": response_format,
                "max_tokens": max_tokens,
                "thinking_disabled": thinking_disabled,
                "system_prompt_chars": len(system_prompt),
                "user_prompt_chars": len(user_prompt),
                "request_body_bytes": body_bytes,
            }
            started = time.perf_counter()
            try:
                with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                ) as response:
                    headers_at = time.perf_counter()
                    response_body = response.read()
                    body_at = time.perf_counter()
                    record["http_status"] = response.status_code
                    record["time_to_headers_ms"] = round((headers_at - started) * 1000, 1)
                    record["body_read_ms"] = round((body_at - headers_at) * 1000, 1)
                    response.raise_for_status()
                parse_started = time.perf_counter()
                response_payload = json.loads(response_body)
                content = response_payload["choices"][0]["message"]["content"]
                parsed = TravelRequest.model_validate_json(content)
                semantic_reasons = validate_travel_request_semantics(parsed)
                parse_finished = time.perf_counter()
                record.update(
                    {
                        "status": "success" if not semantic_reasons else "semantic_invalid",
                        "output_chars": len(content),
                        "json_schema_semantic_ms": round((parse_finished - parse_started) * 1000, 1),
                        "semantic_reason_count": len(semantic_reasons),
                    }
                )
            except Exception as exc:  # Keep benchmark running across transient provider failures.
                record.update({"status": "error", "error_type": type(exc).__name__, "error_message": str(exc)[:300]})
            finally:
                finished = time.perf_counter()
                record["total_ms"] = round((finished - started) * 1000, 1)
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                records.append(record)
                print(f"{index}/{args.runs} {record['status']} {record['total_ms']}ms")
                if index < args.runs and args.sleep_seconds > 0:
                    time.sleep(args.sleep_seconds)

    summary = summarize(records)
    summary.update(
        {
            "label": args.label,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "response_format": response_format,
            "max_tokens": max_tokens,
            "thinking_disabled": thinking_disabled,
            "raw_input_chars": len(args.raw_input),
            "jsonl_path": str(jsonl_path),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
