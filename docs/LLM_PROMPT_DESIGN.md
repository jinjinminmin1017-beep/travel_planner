# AI 出行规划应用 LLM Prompt 设计 V1

版本：V1  
日期：2026-05-26  
对齐文档：

- PRD：AI Travel Planner PRD V2.1
- 系统架构设计：AI Travel Planner System Architecture V1.1
- 核心数据结构与 JSON Schema：AI_Travel_Planner_Data_Schema_V1.15
- 数据源准入规范：AI_Travel_Planner_Data_Source_Governance_V1.1

---

## Changelog

| 日期 | 版本 | 更改点 |
|---|---|---|
| 2026-05-26 | V1 | 创建 LLM Prompt 设计初版，定义 LLM 使用边界、调用链路、Prompt 版本管理、Intent Parser Prompt、Recommendation Prompt、Repair Prompt、Semantic Validator、日志与 Codex 实现要求。 |

---

## 1. 文档目标

本文档用于约束 AI 出行规划应用中 LLM 的使用方式、Prompt 设计、输入输出边界、校验流程和降级策略。

LLM 不是事实数据源。

本系统采用：

```text
确定性候选池 + LLM 受约束推荐与解释
```

即：

1. 后端确定性引擎生成候选方案。
2. LLM 只负责理解自然语言、选择候选方案、生成解释。
3. LLM 不得创造任何车次、航班、票价、余票、时间、路线或跳转信息。
4. 所有 LLM 输出必须经过 JSON Schema 校验和业务语义校验。
5. 修复失败后必须返回推荐不可用状态，不得展示非法输出，也不得用代码生成三张推荐卡。

---

## 2. LLM 使用边界

### 2.1 LLM 可以做什么

LLM 允许用于：

1. 自然语言解析。
2. 用户偏好识别。
3. 出行约束识别。
4. 从候选方案池中选择推荐方案。
5. 解释推荐理由。
6. 总结风险提示。
7. 解释费用、耗时、舒适度之间的取舍。
8. 对非法输出进行一次结构修复。

### 2.2 LLM 不得做什么

LLM 禁止：

1. 编造高铁车次。
2. 编造航班号。
3. 编造票价。
4. 编造余票。
5. 编造舱位库存。
6. 编造出发时间。
7. 编造到达时间。
8. 编造中转站。
9. 编造中转机场。
10. 编造地图路线。
11. 编造打车费用。
12. 编造跳转链接。
13. 修改候选方案中的价格。
14. 修改候选方案中的时间。
15. 修改候选方案中的 risk_level。
16. 选择 `can_be_selected_by_llm = false` 的方案。
17. 选择 `recommendation_eligibility = BLOCKED` 的方案。
18. 宣称“保证有票”。
19. 宣称“补票一定成功”。
20. 宣称“航班中转一定不会误机”。

---

## 3. LLM 调用总览

第一版只保留三类 LLM 调用：

| 调用 | 作用 | 输出 Schema |
|---|---|---|
| Intent Parser | 将自然语言解析为结构化 TravelRequest | TravelRequest Schema V1.15 |
| Recommendation Engine | 从确定性候选池中选择三张推荐卡 | LLMRecommendationOutput Schema V1.15 |
| Repair Prompt | 修复非法 LLM 输出 | 与原调用输出 Schema 相同 |

暂不单独拆出 Explanation Generator。推荐解释、风险摘要和取舍说明由 Recommendation Prompt 生成，后续如复杂度上升再拆为独立调用。

---

## 4. Prompt 版本管理

### 4.1 版本命名

Prompt 版本采用以下格式：

```text
<module_name>_prompt_v<major>.<minor>
```

示例：

```text
intent_parser_prompt_v1.0
recommendation_prompt_v1.0
repair_prompt_v1.0
```

### 4.2 必须记录的元数据

每次 LLM 调用必须记录：

1. `llm_call_id`
2. `request_id`
3. `trace_id`
4. `correlation_id`
5. `prompt_version`
6. `model_name`
7. `schema_version`
8. `input_hash`
9. `output_hash`
10. `schema_validation_result`
11. `semantic_validation_result`
12. `repair_attempted`
13. `final_strategy`
14. `latency_ms`
15. `created_at`

### 4.3 Prompt 与 Schema 的关系

Prompt 文档不得重复定义 JSON Schema。

Prompt 只能引用 Schema 文档中的对象：

```text
TravelRequest Schema V1.15
LLMRecommendationInput Schema V1.15
LLMRecommendationOutput Schema V1.15
LLMValidationResult Schema V1.15
ErrorResponse Schema V1.15
```

如果 Schema 升级，Prompt 必须检查是否需要同步升级。

---

## 5. LLM 调用链路

### 5.1 总体链路

```text
用户自然语言
  ↓
Intent Parser LLM
  ↓
TravelRequest JSON
  ↓
Schema Validator
  ↓
Semantic Validator
  ↓
地点 / 车站 / 机场 / 高铁 / 航班 / 接驳 / 票源增强确定性引擎
  ↓
Candidate Plans
  ↓
LLMRecommendationInput
  ↓
Recommendation LLM
  ↓
LLMRecommendationOutput
  ↓
Schema Validator
  ↓
Semantic Validator
  ↓
合法：生成 RecommendationResult
非法：Repair Prompt 一次
仍非法：推荐结果不可用，返回 PARTIAL 响应
```

### 5.2 核心原则

1. LLM 输入永远是结构化上下文。
2. LLM 输出永远是 JSON。
3. 事实字段永远以数据源和确定性计算为准。
4. LLM 不得越过候选池。
5. LLM 输出不得直接展示，必须经过校验。
6. LLM 输出非法时最多 repair 一次。
7. repair 失败必须进入 deterministic fallback。

---

## 6. Intent Parser Prompt

### 6.1 调用目标

将用户自然语言解析为 `TravelRequest Schema V1.15`。

### 6.2 输入

Intent Parser 输入包括：

1. `schema_version = 1.15`
2. 用户原始自然语言。
3. 当前日期。
4. 默认时区。
5. 默认系统策略。
6. 可选上下文，例如用户已选择“Web App first”。

### 6.3 输出

输出必须符合：

```text
TravelRequest Schema V1.15
```

### 6.4 Intent Parser System Prompt

```text
你是 AI 出行规划应用的自然语言解析器。

你的任务是把用户输入的出行需求解析为 TravelRequest JSON。

必须遵守以下规则：

1. 只输出 JSON，不输出解释性文字。
2. 输出必须符合 TravelRequest Schema V1.15。
3. schema_version 固定为 "1.15"。
4. 不得生成任何高铁车次、航班号、票价、余票、路线方案或推荐方案。
5. 只能解析用户输入中的出发地、目的地、日期、时间、偏好、交通方式限制和乘客偏好。
6. 如果用户未明确指定推荐偏好，则 preferences 必须包含 CHEAPEST、MOST_COMFORTABLE、BALANCED，preference_source = SYSTEM_DEFAULT。
7. 如果用户明确说“只要最便宜”，则 preferences 只包含 CHEAPEST，preference_source = USER_EXPLICIT。
8. 如果用户明确说“只要最舒服”，则 preferences 只包含 MOST_COMFORTABLE，preference_source = USER_EXPLICIT。
9. 如果用户提到“不坐飞机”，必须把 FLIGHT 加入 excluded_transport_modes。
10. 如果用户提到“不坐高铁”，必须把 RAIL 加入 excluded_transport_modes。
11. 如果用户提到“不要机场大巴”或“不要接送机”，必须把 AIRPORT_TRANSFER 加入 excluded_transport_modes。
12. 如果用户提到“不要接送站”，必须把 RAIL_STATION_TRANSFER 加入 excluded_transport_modes。
13. 硬约束写入 hard_constraints。
14. 软偏好写入 soft_preferences。
15. 不确定的字段使用 null 或默认值，不得猜测。
16. 不得生成候选站、候选机场或候选方案。
```

### 6.5 Intent Parser User Prompt Template

```text
请将以下用户出行需求解析为 TravelRequest JSON。

schema_version: 1.15
default_timezone: Asia/Shanghai
current_date: {{current_date}}

用户输入：
{{raw_user_input}}

输出要求：
- 只输出 JSON
- 不要 Markdown
- 不要解释
- 不要生成车次、航班、价格、余票或路线方案
- 必须符合 TravelRequest Schema V1.15
```

### 6.6 Intent Parser 示例

#### 示例 1：用户未指定偏好

用户输入：

```text
我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆到青岛金水假日酒店。
```

期望输出要点：

```json
{
  "schema_version": "1.15",
  "origin_text": "上海嘉定南翔格林公馆",
  "destination_text": "青岛金水假日酒店",
  "travel_date": "2026-05-21",
  "earliest_departure_time": {
    "datetime": "2026-05-21T09:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "source_timezone": "Asia/Shanghai"
  },
  "preferences": ["CHEAPEST", "MOST_COMFORTABLE", "BALANCED"],
  "preference_source": "SYSTEM_DEFAULT"
}
```

#### 示例 2：用户只要最便宜

用户输入：

```text
明天从上海到青岛，只要最便宜的方式，不坐飞机。
```

期望输出要点：

```json
{
  "preferences": ["CHEAPEST"],
  "preference_source": "USER_EXPLICIT",
  "excluded_transport_modes": ["FLIGHT"],
  "soft_preferences": {
    "prefer_low_cost": true
  }
}
```

#### 示例 3：用户有硬预算

用户输入：

```text
5月21号从上海去青岛，预算不要超过1000，晚上8点前到。
```

期望输出要点：

```json
{
  "hard_constraints": {
    "max_total_cost": {
      "amount_minor": 100000,
      "currency": "CNY",
      "scale": 2,
      "is_estimated": false,
      "display_text": "¥1000.00"
    },
    "latest_arrival_time": {
      "datetime": "2026-05-21T20:00:00+08:00",
      "timezone": "Asia/Shanghai",
      "source_timezone": "Asia/Shanghai"
    }
  }
}
```

---

## 7. Recommendation Prompt

### 7.1 调用目标

从确定性候选方案池中选择三张推荐卡：

1. CHEAPEST
2. MOST_COMFORTABLE
3. BALANCED

输出必须符合：

```text
LLMRecommendationOutput Schema V1.15
```

### 7.2 输入

输入必须符合：

```text
LLMRecommendationInput Schema V1.15
```

关键输入字段：

1. `request_id`
2. `travel_request`
3. `candidate_plan_ids`
4. `candidate_plans`
5. `selection_constraints`

### 7.3 输出

输出必须包含三个 RecommendationSlot：

1. CHEAPEST
2. MOST_COMFORTABLE
3. BALANCED

每个 slot 必须满足：

1. 如果 status = AVAILABLE，则 plan_id 必须非 null。
2. 如果 status = NOT_AVAILABLE 或 BLOCKED，则 plan_id 必须为 null。
3. reason 必须非空。
4. 不得省略任何卡位。

### 7.4 Recommendation System Prompt

```text
你是 AI 出行规划应用的推荐选择器。

你的任务是从系统提供的 candidate_plans 中选择三张推荐卡：
1. CHEAPEST
2. MOST_COMFORTABLE
3. BALANCED

必须遵守以下规则：

1. 只输出 JSON，不输出 Markdown，不输出解释性正文。
2. 输出必须符合 LLMRecommendationOutput Schema V1.15。
3. selected_recommendations 必须正好包含 3 个 slot。
4. 三个 slot 必须分别是 CHEAPEST、MOST_COMFORTABLE、BALANCED。
5. 只能选择 input.candidate_plan_ids 中存在的 plan_id。
6. 不得选择 can_be_selected_by_llm = false 的方案。
7. 不得选择 recommendation_eligibility = BLOCKED 的方案。
8. 不得选择 plan_lifecycle_status = EXPIRED / INVALIDATED 的方案。
9. 不得修改任何 candidate_plans 中的事实字段。
10. 不得新增车次、航班、票价、余票、时间、路线、跳转链接。
11. 不得声称保证有票。
12. 不得声称补票一定成功。
13. 不得声称航班中转一定不会误机。
14. 如果某类推荐没有可用方案，必须输出该 slot，status = NOT_AVAILABLE 或 BLOCKED，plan_id = null，并说明原因。
15. reason 必须基于 candidate_plans 中已有字段，例如 total_cost、duration、comfort_score、risk_assessment、data_quality。
16. 不得使用候选方案之外的信息。
```

### 7.5 Recommendation User Prompt Template

```text
请基于以下 LLMRecommendationInput，从 candidate_plans 中选择三张推荐卡。

schema_version: 1.15

输入：
{{llm_recommendation_input_json}}

输出要求：
- 只输出 JSON
- 不要 Markdown
- 不要解释性正文
- 必须符合 LLMRecommendationOutput Schema V1.15
- 只能引用 candidate_plan_ids 中的 plan_id
- 不得修改价格、时间、车次、航班、余票和数据源
```

---

## 8. Recommendation 选择规则

### 8.1 Cheapest

优先选择：

1. `recommendation_eligibility = ELIGIBLE`
2. `can_be_selected_by_llm = true`
3. `risk_assessment.overall_risk_level != BLOCKED`
4. `cost_breakdown.total_cost.amount_minor` 最低
5. 如果费用相近，选择风险更低、耗时更短的方案

不得选择：

1. BLOCKED 方案
2. EXPIRED 方案
3. INVALIDATED 方案
4. 买短补长高风险方案
5. 数据源安全关键缺失方案

### 8.2 Most Comfortable

优先选择：

1. `comfort_score.total_score` 最高
2. 风险等级低
3. 换乘少
4. 等待压力低
5. 行李友好
6. 接驳复杂度低
7. 舱位/座席更舒适

不得仅因为飞行时间短就认定最舒适。必须考虑：

1. 到机场时间
2. 值机安检时间
3. 航班延误风险
4. 机场到目的地接驳
5. 航班中转风险

### 8.3 Balanced

综合考虑：

1. 费用
2. 总耗时
3. 舒适度
4. 风险
5. 数据质量
6. 用户 hard_constraints
7. 用户 soft_preferences

Balanced 不一定是 cheapest，也不一定是 most_comfortable。

---

## 9. LLM 输出校验流程

### 9.1 校验顺序

```text
LLM raw output
  ↓
JSON parse
  ↓
JSON Schema validation
  ↓
Business semantic validation
  ↓
合法：进入 RecommendationResult
  ↓
非法：Repair Prompt 一次
  ↓
仍非法：推荐结果不可用，返回 PARTIAL 响应
```

### 9.2 JSON Schema 校验

校验内容：

1. 是否为 JSON。
2. 是否符合 LLMRecommendationOutput Schema V1.15。
3. 是否包含 schema_version。
4. selected_recommendations 是否为 3 个。
5. recommendation_type 是否合法。
6. status 是否合法。
7. plan_id 类型是否合法。

### 9.3 Semantic Validator 校验

必须实现以下规则：

| 规则 ID | 规则 |
|---|---|
| REC-001 | `selected_recommendations.length == 3` |
| REC-002 | recommendation_type 集合必须等于 `{CHEAPEST, MOST_COMFORTABLE, BALANCED}` |
| REC-003 | `status = AVAILABLE` 时，`plan_id != null` |
| REC-004 | `status = NOT_AVAILABLE` 或 `BLOCKED` 时，`plan_id == null` 且 `reason` 非空 |
| REC-005 | `status = AVAILABLE` 的 plan_id 必须属于 input.candidate_plan_ids |
| REC-006 | selected plan 必须满足 `can_be_selected_by_llm == true` |
| REC-007 | selected plan 必须满足 `recommendation_eligibility != BLOCKED` |
| REC-008 | selected plan 不得为 `plan_lifecycle_status = EXPIRED / INVALIDATED` |
| REC-009 | LLM 不得修改价格、时间、车次、航班、余票、数据源等事实字段 |
| REC-010 | candidate_plan_ids 与 candidate_plans[*].plan_id 集合必须完全一致 |
| REC-011 | LLM 输入候选池不得超过 15 个方案 |
| REC-012 | 三个 slot 不得重复 recommendation_type |

---

## 10. Repair Prompt

### 10.1 触发条件

以下情况触发 Repair Prompt：

1. LLM 输出不是 JSON。
2. JSON Schema 校验失败。
3. 三个推荐卡位缺失。
4. plan_id 不在候选池。
5. 选择了 BLOCKED 方案。
6. 选择了不可被 LLM 选择的方案。
7. reason 为空。
8. 输出包含候选池外事实。
9. 修改了候选方案事实字段。

### 10.2 修复次数

最多修复一次：

```text
max_repair_attempts = 1
```

不得无限重试。

### 10.3 Repair System Prompt

```text
你上一次输出不符合系统要求。请基于错误原因修复输出。

必须遵守：

1. 只输出 JSON。
2. 必须符合目标 Schema。
3. 不要解释。
4. 只能使用系统提供的 candidate_plan_ids。
5. 不得选择 BLOCKED、EXPIRED、INVALIDATED 或 can_be_selected_by_llm = false 的方案。
6. 不得新增或修改任何车次、航班、价格、时间、余票、数据源。
7. 若某推荐类型没有合法方案，必须输出对应 slot，status = NOT_AVAILABLE 或 BLOCKED，plan_id = null。
```

### 10.4 Repair User Prompt Template

```text
你的上一次输出非法。

错误原因：
{{invalid_reasons}}

原始 LLM 输出：
{{raw_llm_output}}

合法候选 plan_id：
{{candidate_plan_ids}}

候选方案摘要：
{{candidate_plan_summaries}}

请重新输出符合 {{target_schema_name}} 的 JSON。
```

---

## 11. 推荐不可用处理

### 11.1 触发条件

以下情况进入推荐不可用处理：

1. LLM 调用超时。
2. LLM 输出非法。
3. Repair Prompt 后仍非法。
4. LLM 服务不可用。
5. LLM 输出选择不合法方案。
6. LLM 输出被 Semantic Validator 拒绝。

### 11.2 Cheapest Fallback

选择：

```text
recommendation_eligibility = ELIGIBLE
can_be_selected_by_llm = true
plan_lifecycle_status not in [EXPIRED, INVALIDATED]
risk != BLOCKED
total_cost 最低
```

若无可用方案：

```text
status = NOT_AVAILABLE
plan_id = null
reason = "当前没有满足条件的最优惠方案。"
```

### 11.3 Most Comfortable Fallback

选择：

```text
comfort_score.total_score 最高
recommendation_eligibility = ELIGIBLE
can_be_selected_by_llm = true
risk != BLOCKED
```

若舒适度相同：

1. 风险更低优先。
2. 中转更少优先。
3. 总耗时更短优先。

### 11.4 Balanced Fallback

建议综合分：

```text
balanced_score =
  comfort_score_normalized * 0.35
+ cost_score_normalized * 0.25
+ duration_score_normalized * 0.20
+ risk_score_normalized * 0.20
```

如果用户明确偏好最便宜：

```text
cost_score 权重可提高
```

如果用户明确偏好最舒适：

```text
comfort_score 权重可提高
```

### 11.5 输出

LLM 推荐不可用、输出非法或 Repair 仍失败时，不得由代码生成最便宜、最舒适、综合推荐三张卡。

后端应返回：

- `recommendation_result = null`
- `planning_status = PARTIAL`
- `missing_components` 包含 `recommendation_result`
- `source_failures` 记录 `real_llm` 不可用或输出非法
- 用户仍可查看候选方案列表，但不展示三张推荐卡

---

## 12. Intent Parser Semantic Validator

Intent Parser 输出 TravelRequest 后，必须进行语义校验。

### 12.1 必须校验

1. origin_text 非空。
2. destination_text 非空。
3. travel_date 合法。
4. preferences 非空。
5. hard_constraints 存在。
6. soft_preferences 存在。
7. allowed_transport_modes 和 excluded_transport_modes 不冲突。
8. 如果用户明确排除某交通方式，不能再加入 allowed only 模式。
9. Money 必须使用 amount_minor / currency / scale。
10. TimePoint 必须有 timezone。
11. 不得出现车次、航班、价格、余票等事实字段。

### 12.2 修复策略

如果 Intent Parser 输出非法：

1. Repair Prompt 一次。
2. 仍非法则返回 ErrorResponse。
3. user_visible_message 提示用户补充信息或重新输入。

---

## 13. 日志与可观测性

每次 LLM 调用必须记录：

```json
{
  "llm_call_id": "llm_001",
  "request_id": "req_001",
  "trace_id": "trace_001",
  "correlation_id": "corr_001",
  "prompt_version": "recommendation_prompt_v1.0",
  "schema_version": "1.15",
  "model_name": "model_name",
  "latency_ms": 1200,
  "schema_valid": true,
  "semantic_valid": true,
  "repair_attempted": false,
  "final_strategy": "USE_ORIGINAL"
}
```

不得记录：

1. 第三方账号。
2. 支付信息。
3. 身份证号。
4. 乘客实名信息。
5. 未脱敏 token。
6. 未脱敏 API key。

---

## 14. Prompt 安全规则

### 14.1 输入安全

传给 LLM 的输入应尽量最小化。

Recommendation Prompt 不应传：

1. 第三方 token。
2. API key。
3. 内部成本。
4. 商务合同信息。
5. 用户敏感身份信息。

### 14.2 输出安全

LLM 输出必须：

1. 结构化。
2. 可校验。
3. 可追踪。
4. 不包含未知字段。
5. 不包含事实创造。
6. 不包含交易承诺。

---

## 15. Codex 实现要求

Codex 必须实现：

1. Prompt 模板文件。
2. Prompt version 常量。
3. LLM client wrapper。
4. JSON parse。
5. JSON Schema validation。
6. Semantic Validator。
7. Repair Prompt 一次。
8. LLM 推荐不可用时返回 PARTIAL 且不生成三张推荐卡。
9. LLMValidationResult。
10. LLM 调用日志。
11. 单元测试。
12. golden test cases。

Codex 不得：

1. 让 LLM 直接生成 TravelPlan。
2. 跳过 Schema 校验。
3. 跳过 Semantic Validator。
4. 让 LLM 查询数据源。
5. 让 LLM 修改候选方案。
6. 让 LLM 输出前端最终展示对象而不校验。
7. 在失败时静默吞掉错误。

---

## 16. 文件建议

建议后续代码结构：

```text
backend/
  app/
    llm/
      prompts/
        intent_parser_prompt_v1_0.txt
        recommendation_prompt_v1_0.txt
        repair_prompt_v1_0.txt
      validators/
        schema_validator.py
        semantic_validator.py
      client.py
      models.py
      logs.py
```

---

## 17. 测试用例

### 17.1 Intent Parser 测试

| 用例 | 输入 | 期望 |
|---|---|---|
| 默认三类推荐 | 未说偏好 | preferences = 三类，preference_source = SYSTEM_DEFAULT |
| 只要最便宜 | “只要最便宜” | preferences = CHEAPEST |
| 不坐飞机 | “不坐飞机” | excluded_transport_modes 包含 FLIGHT |
| 不要接送机 | “不要机场大巴/接送机” | excluded_transport_modes 包含 AIRPORT_TRANSFER |
| 硬预算 | “不要超过1000” | hard_constraints.max_total_cost |
| 最晚到达 | “晚上8点前到” | hard_constraints.latest_arrival_time |
| 不确定信息 | 缺少日期 | 返回 ErrorResponse 或要求补充 |

### 17.2 Recommendation 测试

| 用例 | 条件 | 期望 |
|---|---|---|
| 正常三卡 | 候选方案充足 | 输出三张 slot |
| 缺最便宜 | 无 eligible low-cost plan | CHEAPEST status = NOT_AVAILABLE |
| BLOCKED 方案 | 候选含 BLOCKED | 不得选择 |
| 不可被 LLM 选 | can_be_selected_by_llm = false | 不得选择 |
| 过期方案 | EXPIRED | 不得选择 |
| LLM 输出少于 3 个 slot | 非法 | Repair |
| Repair 仍失败 | 非法 | recommendation_result = null |
| LLM 修改价格 | 非法 | Reject |

---

## 18. 验收标准

### 18.1 Prompt 验收

1. 每个 Prompt 有版本。
2. 每个 Prompt 引用 Schema V1.15。
3. Prompt 不重复定义 Schema。
4. Prompt 明确禁止编造事实。
5. Prompt 明确只输出 JSON。

### 18.2 校验验收

1. LLM 输出必须通过 JSON Schema 校验。
2. LLM 输出必须通过 Semantic Validator。
3. plan_id 必须来自候选池。
4. BLOCKED 不得被选择。
5. 不可选方案不得被选择。
6. 过期方案不得被选择。

### 18.3 降级验收

1. Repair 最多一次。
2. Repair 失败进入 deterministic fallback。
3. fallback 仍输出三卡位模型。
4. fallback reason 使用模板。
5. fallback 结果可被前端展示。

---

## 19. 后续待细化

后续可以继续细化：

1. Prompt few-shot 样例库。
2. Intent Parser 多轮补充信息策略。
3. 多语言 Prompt。
4. Explanation Generator 独立拆分。
5. 个性化偏好权重。
6. LLM 成本控制策略。
7. LLM A/B 测试策略。
