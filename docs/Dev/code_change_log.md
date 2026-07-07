## 2026-07-07 23:16:02 +08:00

- 任务：ARC-20260707-02 为真实 LLM 调用关闭 Thinking 并限制输出 token。
- 代码提交：`282cb4a117e1cc8e9ff774c0f434d23bbe3412c7`。
- 修改内容：
  - 在真实 LLM Provider 请求体中默认加入 `thinking={"type":"disabled"}`。
  - 新增 `REAL_LLM_MAX_TOKENS` 读取，默认 `800`，非法值或小于 1 时回退默认值。
  - 保留 `temperature=0` 与 `response_format={"type":"json_object"}`。
  - `.env.example` 新增 `REAL_LLM_MAX_TOKENS=800`。
  - `scripts/benchmark_intent_llm_latency.py` 同步生产请求参数，记录 `max_tokens` 与 `thinking_disabled`。
  - 补充 LLM provider 请求体单元测试。
- 验证：
  - `.\.venv\Scripts\python -m py_compile scripts\benchmark_intent_llm_latency.py backend\app\data_sources\llm_providers.py`：通过。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_data_sources.py -q`：通过，15 passed。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_recommendation_engine.py -q`：通过，11 passed。
  - 真实 key 普通短句 smoke：HTTP 200，`finish_reason=stop`，content 非空；model=`glm-4.5-air`，timeout=`45.0`，max_tokens=`800`，thinking_disabled=`true`，total_ms=`4226.2`。
  - 真实 key Intent Parser benchmark：1/1 success；model=`glm-4.5-air`，timeout=`45.0`，max_tokens=`800`，thinking_disabled=`true`，total_ms=`6816.3`。

## 2026-07-07 22:03:06 +08:00

- 任务：ARC-20260707-01 精简并落地 LLM Intent / Recommendation Prompt。
- 代码提交：`8088dddb2e200deaec5e9e1af4aad49be110a426`。
- 修改内容：
  - 重写 Intent Parser、Recommendation、Repair system prompt，改为最小字段契约和明确禁止项。
  - 调整 OpenAI 兼容 LLM provider 的 user prompt 拼接，保留 `response_format={"type":"json_object"}`。
  - Recommendation repair 再次列出合法 `plan_id` 清单，并携带上一轮原始 LLM 输出。
  - 更新推荐引擎测试，覆盖 intent prompt 动态字段、TimePoint 要求、合法 `plan_id` 清单、compact selection payload 和 repair prompt。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_recommendation_engine.py -q`：通过，11 passed。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_api.py -q`：通过，40 passed。
