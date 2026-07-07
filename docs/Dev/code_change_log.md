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
