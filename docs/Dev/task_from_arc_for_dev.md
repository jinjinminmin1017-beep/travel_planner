## ARC-20260707-01 精简并落地 LLM Intent / Recommendation Prompt

来源：架构任务，2026-07-07。

完成状态：已完成。完成时间：2026-07-07 22:03:06 +08:00。代码提交：`8088dddb2e200deaec5e9e1af4aad49be110a426`。

### 背景

`docs/old/LLM_PROMPT_DESIGN.md` 已更新到 V1.2。核心口径：

- `LLM_PROMPT_DESIGN.md` 是设计文档，不直接进入 LLM input。
- 运行时只发送 `backend/app/llm/prompts/*.txt` 中的 system prompt，以及 `backend/app/data_sources/llm_providers.py` 拼接的 user prompt。
- `TravelRequest Schema V1.15`、`LLMRecommendationOutput Schema V1.15` 只是后端校验契约名称，不能假设 LLM 天然理解完整 Schema。
- Prompt 只提供当前任务所需的最小字段契约、关键枚举和禁止项；完整合法性仍由 Schema Validator / Semantic Validator 保证。

### 修改范围

只改后端 LLM Prompt 与相关测试，除非测试暴露必要问题，不要改业务 schema。

- `backend/app/llm/prompts/intent_parser_prompt_v1_0.txt`
- `backend/app/llm/prompts/recommendation_prompt_v1_0.txt`
- `backend/app/llm/prompts/repair_prompt_v1_0.txt`
- `backend/app/data_sources/llm_providers.py`
- `backend/app/tests/test_api.py`
- `backend/app/tests/test_recommendation_engine.py`
- 如已有 prompt 专项测试，优先补在现有测试文件中；不要新增大而散的测试目录。

### Intent Parser Prompt 要求

- System prompt 只描述自然语言意图解析任务。
- 保留 `schema_version = "1.15"`。
- 明确 `request_id` 和 `raw_user_input` 必须从 user prompt 逐字复制。
- 给出最小字段清单：`schema_version`、`request_id`、`raw_user_input`、`origin_text`、`destination_text`、`travel_date`、`time_anchor_type`、`time_window_start`、`time_window_end`、`earliest_departure_time`、`latest_arrival_time`、`preferred_departure_time`、`preferences`、`preference_source`、`hard_constraints`、`soft_preferences`、`preferred_rail_seat`、`preferred_flight_cabin`。
- 明确 TimePoint 必须是对象：`datetime`、`timezone`、`source_timezone`，不得输出 `"08:00"` 这类字符串。
- 明确缺失字段不要猜测；缺出发地/目的地/日期时允许输出空字符串或 null，交由后端校验与补充信息流程处理。
- 禁止生成车次、航班、票价、余票、候选站、候选机场、路线方案、接驳方案或推荐方案。
- User prompt 保留动态字段：`schema_version`、`request_id`、`default_timezone`、`current_date`、用户原始输入和简短输出要求。

### Recommendation Prompt 要求

- System prompt 只描述从候选摘要中选择三张推荐卡。
- 顶层字段只能允许：`schema_version`、`selected_recommendations`、`validation_blockers`、`explanation`。
- 禁止顶层字段：`request_id`、`recommendations`、`candidate_plan_ids`、`candidate_plans`。
- `selected_recommendations` 必须正好包含 CHEAPEST、MOST_COMFORTABLE、BALANCED 三个 slot。
- 每个 slot 只包含：`schema_version`、`recommendation_type`、`status`、`plan_id`、`reason`。
- AVAILABLE 的 `plan_id` 必须逐字复制 user prompt 中合法 `plan_id` 清单的某一行。
- NOT_AVAILABLE 或 BLOCKED 的 `plan_id` 必须为 null，且 `reason` 非空。
- 不得在 system prompt 或 JSON 示例中写入可被照抄的 `plan_id` 占位符，例如 `"从合法 plan_id 中选择"`。
- User prompt 必须继续单独列出合法 `plan_id` 清单，并传入 compact `LLMRecommendationSelectionInput JSON`。
- 不得传完整 `TravelPlan` 或完整 JSON Schema 给 LLM。

### Repair Prompt 要求

- Intent repair 和 Recommendation repair 共用文件时，`llm_providers.py` 的 user prompt 必须补足目标 schema 名称、错误原因、原始输出和最小动态上下文。
- Recommendation repair 必须再次列出合法 `plan_id` 清单。
- Repair 不得引导模型创造候选池外事实。

### 测试要求

- 增加或更新 Intent Parser prompt 测试，覆盖：
  - prompt 不要求模型“自行理解完整 TravelRequest Schema V1.15”。
  - `time_window_start/time_window_end` 要求 TimePoint 对象，不允许字符串时间窗口。
  - user prompt 包含 `request_id`、`current_date`、`default_timezone` 和用户原文。
- 增加或更新 Recommendation prompt 测试，覆盖：
  - system prompt 不包含可照抄的 `plan_id` 占位符。
  - user prompt 单独列出合法 `plan_id` 清单。
  - compact selection payload 不包含完整 `TravelPlan`。
  - repair user prompt 也列出合法 `plan_id` 清单。
- 保留现有 schema/semantic validator 测试：REC-001 至 REC-012 不得回退。

### 验收标准

- 真实 LLM 调用仍使用 `response_format={"type":"json_object"}`。
- LLM input 中不包含 `LLM_PROMPT_DESIGN.md` 全文。
- Intent Parser 不再依赖抽象 Schema 名称作为主要输出指导。
- Recommendation Prompt 不包含 plan_id 占位符模板。
- LLM 仍不能生成或修改车次、航班、票价、余票、时间、路线、跳转链接和候选方案事实字段。
- 执行后端测试，至少包含：
  - `python -m pytest backend/app/tests/test_api.py`
  - `python -m pytest backend/app/tests/test_recommendation_engine.py`
