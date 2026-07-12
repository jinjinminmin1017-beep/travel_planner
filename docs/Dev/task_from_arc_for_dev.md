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

---

## ARC-20260707-02 为真实 LLM 调用关闭 Thinking 并限制输出 token

来源：架构任务，2026-07-07。

完成状态：已完成。完成时间：2026-07-07 23:16:02 +08:00。代码提交：`282cb4a117e1cc8e9ff774c0f434d23bbe3412c7`。

### 背景

真实 LLM 意图解析耗时专项测试发现：

- `glm-4.7-flash` 在完整 Intent Parser prompt 下串行 10 组测试：`0/10` 成功，1 次 `ReadTimeout`，9 次 `429`。
- 用户更新模型为 `glm-4.5-air` 后，完整 Intent Parser prompt 单次测试仍 `ReadTimeout`，总耗时约 `52.7s`。
- 不发送 Intent Parser prompt，仅发送普通短句时，`glm-4.5-air` 可在约 `6.3s-9.2s` 返回。
- 普通短句不关闭 thinking 时曾出现 `HTTP 200` 但 `finish_reason=length` 且 `content` 为空；显式设置 `thinking={"type":"disabled"}` 后可正常返回内容。

智谱 GLM 官方对话补全接口支持在请求体顶层关闭 thinking：

```json
{
  "thinking": {
    "type": "disabled"
  }
}
```

当前 `backend/app/data_sources/llm_providers.py` 的 `_complete_json()` 只发送 `model`、`temperature`、`response_format`、`messages`，未设置 `thinking`，也未设置 `max_tokens`。对意图解析这类信息抽取任务，thinking 会增加延迟和输出不确定性，不应默认启用。

### 修改范围

只改真实 LLM Provider 请求体、配置读取和相关测试，不改 API contract，不改业务 schema。

- `backend/app/data_sources/llm_providers.py`
- `.env.example`
- `backend/app/tests/test_data_sources.py` 或现有 LLM provider 相关测试文件
- `scripts/benchmark_intent_llm_latency.py` 如需与生产调用参数保持一致，可同步补充默认参数读取

### 开发要求

- 在 `OpenAICompatibleLLMProvider._complete_json()` 的请求 JSON 顶层加入：
  - `"thinking": {"type": "disabled"}`
- 增加 `REAL_LLM_MAX_TOKENS` 环境变量读取：
  - 默认建议 `800`。
  - 非法值或小于 1 时回退默认值。
  - 写入请求体字段 `"max_tokens": <int>`。
- 不要把 `thinking` 放进 `messages`。
- 不要把 `thinking` 放进 prompt 文本。
- 继续保留：
  - `"temperature": 0`
  - `"response_format": {"type": "json_object"}`
- 不要在日志中输出 API key、完整 prompt、完整 LLM 输出。
- 如果 `scripts/benchmark_intent_llm_latency.py` 用于对照真实链路，需支持读取同一个 `REAL_LLM_MAX_TOKENS` 默认值，并允许命令行参数覆盖。

### 配置要求

在 `.env.example` 的 Real LLM provider 区块新增：

```env
REAL_LLM_MAX_TOKENS=800
```

现有 `.env` 实际值由用户本地配置，不要提交真实 key。

### 测试要求

补充或更新单元测试，覆盖：

- LLM provider 请求体包含 `thinking={"type":"disabled"}`。
- LLM provider 请求体包含 `max_tokens`，默认值为 `800`。
- `REAL_LLM_MAX_TOKENS` 可覆盖默认值。
- `REAL_LLM_MAX_TOKENS` 非法时回退默认值。
- 现有 `response_format={"type":"json_object"}` 没有被移除。

### 验收标准

- 运行并通过相关后端测试，至少包含：
  - `python -m pytest backend/app/tests/test_data_sources.py`
  - 如新增或修改 LLM provider 专项测试，运行对应测试文件。
- 使用真实 key 的本地 smoke 至少跑 1 次普通短句请求，确认：
  - HTTP 200。
  - `finish_reason=stop`。
  - `content` 非空。
- 使用真实 key 的本地 smoke 至少跑 1 次 Intent Parser benchmark，记录：
  - model。
  - timeout。
  - max_tokens。
  - thinking disabled 是否生效。
  - total_ms。
  - 成功/失败类型。

### 风险与回滚

- 风险：部分非智谱 OpenAI-compatible Provider 可能不接受顶层 `thinking` 字段。
- 推荐实现：仅当 `REAL_LLM_THINKING_DISABLED` 未显式设为 `false` 时发送 `thinking={"type":"disabled"}`，默认关闭；或至少保证当前智谱 GLM 配置可用。
- 回滚方式：移除请求体中的 `thinking` 字段，保留 `max_tokens` 配置不影响 OpenAI-compatible 常见接口。

---

## ARC-20260712-01 实现约束无匹配分析与最近备选

来源：架构任务，2026-07-12。

完成状态：已完成。完成时间：2026-07-12 08:41:29 +08:00。代码提交：因工作区包含用户既有未提交改动，尚未创建可安全归属的提交。

### 背景

当前真实候选全部被时间、预算或交通方式硬约束过滤后，会返回 `FAILED + plans=[]`。需要区分系统失败与业务无匹配，并向用户返回安全、可验证、可解释的最近备选。

详细目标设计见：

- `docs/ARCHITECTURE.md` “约束无匹配与最近备选架构”
- `docs/API_CONTRACT.md` “约束无匹配目标契约（V1.16）”

### 开发范围

- 后端 Schema：`backend/app/models/schemas.py`
- 约束模块：`backend/app/services/constraints/`
- 编排：`backend/app/services/planner.py`
- 候选生成：`backend/app/services/candidate_generator.py`
- 异步状态：`backend/app/main.py`
- 持久化/可观测性：`backend/app/services/store.py`、`persistence.py`、`observability.py`
- 前端类型/API：`frontend/src/types/index.ts`、`frontend/src/api/client.ts`
- 前端页面：优先新增独立约束无匹配组件，避免继续堆入 `App.tsx`
- 导出 Schema：`schemas/*.schema.json`

### 后端任务

1. 将 schema version 升级到 `1.16`，增加 `PlanningStatus.NO_MATCH`、`ConstraintAnalysis`、`CoverageItem`、`RelaxationAlternative`、`ConstraintViolation` 和分类型 `Deviation`。
2. 新建约束模块，实现时间、预算、交通方式、席位/舱位计算器的统一接口。
3. 实现安全/合规门禁；核心事实不完整、`RiskLevel.BLOCKED` 的方案不得作为备选。
4. 从 `planner.py`、`candidate_generator.py` 移除重复硬约束判断，统一消费约束评估结果。
5. 保留过滤前可靠候选；正常候选为空时执行 Pareto 筛选和三个赛道选择，最多返回 3 条并按 plan_id 去重。
6. `NO_MATCH` 返回 `plans=[]`、`recommendation_result=null`；备选 plan 使用 `recommendation_eligibility=NOT_RECOMMENDED`、`can_be_selected_by_llm=false`。
7. 异步 `NO_MATCH` 映射到 `AsyncJobStatus.COMPLETE`，不能映射为 FAILED。
8. 使用确定性模板生成摘要，并根据 coverage 限定“铁路中最早”或“所有已验证方式中最早”等结论。
9. 增加功能开关，关闭时保留旧的失败行为，便于灰度和回滚。
10. 增加结构化日志与指标：候选数、过滤数、备选数、违反类型、coverage、NO_MATCH 次数；不记录完整用户输入或敏感数据。

### 前端任务

1. 同步 V1.16 类型和 `NO_MATCH` 枚举。
2. 轮询把 `NO_MATCH + job COMPLETE` 识别为正常终态，新增 `PLANNING_NO_MATCH` 埋点，不得记为规划失败或普通成功。
3. 新增约束无匹配页面，显示后端 summary、coverage、偏差和最多 3 个备选赛道。
4. 备选卡持续显示“不满足原始要求”，不得混入正常推荐卡。
5. 用户可以查看备选详情；未确认放宽前隐藏/禁用购票跳转。
6. 用户确认后，根据结构化 violation 更新 `TravelRequest` 并发起新的异步规划，不直接把备选提升成正常方案。
7. `NO_SAFE_ALTERNATIVE` 只显示约束说明与修改需求入口。

### 非目标

- 不让 LLM 计算偏差、决定安全门禁或选择放宽规则。
- 不实现跨单位通用总分。
- 第一期不引入数据库迁移。
- 第一期不实现余票人数、无障碍、签证等尚无稳定结构化输入的计算器。

### 验收标准

- 查询完成但无匹配时返回 HTTP 200 + `planning_status=NO_MATCH`。
- 当前温州到武汉 18:00 前到达案例能返回已验证铁路中最早到达备选；航班未启用时明确限定结论范围。
- 危险换乘和核心事实不完整方案不会进入备选。
- “晚到 10 分钟/不超预算”和“按时/超预算 20 元”可并列存在，不产生跨单位总分。
- 正常 COMPLETE/PARTIAL 结果不回退。
- 执行并通过后端测试、前端 typecheck、前端 helper tests 和 schema export diff 检查。

### 风险与回滚

- 前后端必须同步发布 V1.16；新枚举会影响穷举逻辑。
- 通过功能开关关闭 constraint analysis 后回到旧行为。
- 回滚不得修改现有 Provider、推荐和正常结果结构。
