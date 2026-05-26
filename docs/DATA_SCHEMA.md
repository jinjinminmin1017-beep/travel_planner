# AI 出行规划应用核心数据结构与 JSON Schema

版本：V1.15 | 日期：2026-05-26

## Changelog

| 日期 | 版本 | 更改点 |
|---|---|---|
| 2026-05-23 | V1.1 | 补充异步规划状态、中转信息、前端交互、重算接口、数据质量、缺失方案说明、数据源配置、LLM 推荐输入输出。 |
| 2026-05-24 | V1.2 | 增加 schema_version、生命周期、trace_id/correlation_id、Money 精度、TimePoint、hard/soft constraints、缓存、可解释性和可观测字段。 |
| 2026-05-24 | V1.3 | 新增 Plan Lifecycle、版本兼容策略、Deterministic Rule Engine、Idempotency、Timeline、Async Job、Cache Strategy、ExecutionTrace。 |
| 2026-05-24 | V1.4 | 修正 CostBreakdown.total_cost、Money.scale、PlanningStatus 与 JobStatus 分离、DataSourceConfig 正式化、Recalculate 粒度。 |
| 2026-05-24 | V1.5 | 同步 Recalculate 示例、强化 DataSourceConfig、增强 LLM 输出约束、强制 TravelPlanResponse 挂载失败影响范围。 |
| 2026-05-25 | V1.6 | 统一金额字段、TransportMode 枚举、SourceFailure required、TravelPlan 推荐资格、LLM candidate_plan_ids 输入侧约束、additionalProperties: false、Recalculate selected_option。 |
| 2026-05-25 | V1.7 | 修复 NormalizedScores 缺失、SourceFailure.failure_id 缺失、LocalTransferSegment 与架构输出对齐、补齐 API 层响应 Schema、增强 RecalculateResponse 差异摘要、DataQuality 使用 MissingComponentType、ComfortScore 分数范围、LLMRecommendationOutput min/max、TravelPlanResponse.async_job 可为 null、TravelRequest 时间字段使用 TimePoint、Seat/Cabin selected option id。 |
| 2026-05-25 | V1.8 | 收紧 RecommendationResult.recommendations，新增 RecommendationSlot 三卡位状态模型；TravelPlanResponse.recommendation_result 支持异步/失败状态下为 null；结构化 RiskItem；结构化 TravelHardConstraints 与 TravelSoftPreferences；补充统一 ErrorResponse；明确 RecalculateResponse 推荐结果返回规则；增加机器可读 JSON Schema 交付物约定。 |
| 2026-05-26 | V1.9 | 修复 V1.8 冻结前一致性问题：统一推荐三卡位 min/max 描述；补强 LLM 推荐语义校验规则；将 TravelRequest.hard_constraints 与 soft_preferences 纳入 required；限制 LLM 候选池 1–15；统一 SourceFailure 与架构日志字段命名；增强 BookingRedirect 跳转条件与交易边界；明确所有 API 错误路径必须复用 ErrorResponse；更新冻结判断为开发冻结版本。 |
| 2026-05-26 | V1.10 | 基于系统架构 V1.1 再次冻结前 Review：修复 HealthResponse 缺少 schema_version；补充冻结前/冻结后版本兼容边界；将 /api/data-sources/status 从配置对象改为运行状态对象；补充 DataSourceRuntimeStatus；为 RecalculateResponse 回传 trace_id/correlation_id/idempotency_key；新增 RecommendationSlotStatus 枚举；补强 API 响应统一规则与数据源状态语义规则。 |
| 2026-05-26 | V1.11 | 冻结前最终一致性修复：补齐主要业务 API 成功响应中的 trace_id/correlation_id/idempotency_key 透传字段；为 BookingRedirectResponse 增加 generated_at；将 MissingPlanExplanation.plan_type 收紧为 PlanType 枚举；补充 LLM 候选池 5–15 的正常路径语义规则与少于 5 条的降级例外；修正文档中 V1.9/V1.10 遗留描述、机器可读交付物路径和冻结判断版本。 |
| 2026-05-26 | V1.12 | 冻结前二次 Review 修复：将 RecommendationSlot 状态与 plan_id/reason 的条件关系提升为 JSON Schema 可校验规则；为 RecalculateRequest 增加 change_type 与 selected_option.option_type 的一致性约束；收紧 DataSourceMetadata 必填审计字段；补全机器可读 Schema 交付物清单；重写修复落实表，移除 V1.9/V1.10 历史描述混杂；更新冻结判断为 V1.12。 |
| 2026-05-26 | V1.13 | 基于系统架构 V1.1 冻结前最终 Review：强制候选站点、机场、交通分段、座席/舱位选项、费用明细输出 DataSourceMetadata；为 seat_options/cabin_options/data_sources 增加 minItems；补充选中座席/舱位与 option_id 的语义校验规则；将推荐 reason 收紧为非空；修正文档中 V1.9/V1.12 当前版本遗留描述；更新冻结判断为 V1.13。 |
| 2026-05-26 | V1.14 | 基于系统架构 V1.1 与 V1.13 Schema 冻结前补充 Review：修复 ErrorResponse 中 `retryable`、`details` 与错误响应规则不一致的问题；将机器可读交付说明中的 V1.12 遗留描述更新为 V1.14；修正 RecommendationSlot 描述中的 V1.12 遗留表述；补充跳转请求语义规则；更新 schema_version const、冻结判断和修复落实表为 V1.14。 |
| 2026-05-26 | V1.15 | 冻结前收口 Review：补齐 SourceFailure 与 API 链路追踪字段的一致性，增加 `trace_id`、`correlation_id`、`source_used_id`、`fallback_reason`；为 DataSourceStatusResponse 补充 `idempotency_key` 透传字段；将冻结判断中的“已覆盖/已通过 CI”等未执行结论改为“冻结前必须验证”，避免把待验证事项写成完成事实；更新 schema_version const、交付路径和冻结判断为 V1.15。 |

---

## 1. 维护原则

1. 本文档是所有 JSON Schema 的唯一维护源。
2. PRD、系统架构、LLM Prompt 文档不得重复定义 Schema，只能引用本文档的版本。
3. 所有核心对象默认 `additionalProperties: false`。
4. 所有金额字段必须使用 `Money` 或 `MoneyDelta`，不得使用 `number` / `float` 表示金额。
5. LLM 只允许引用确定性候选池内的 `plan_id`，不得生成事实字段。
6. 当前版本用于 Codex 后端模型、前端 TypeScript 类型和接口合同实现。V1.15 是 V1.x 开发冻结候选版本。
7. JSON Schema 负责字段、类型、枚举和基础结构校验；跨字段、跨数组、跨对象一致性必须由后端 Semantic Validator 与单元测试补齐。
8. V1.15 冻结交付时必须同时导出机器可读 JSON Schema 文件，Markdown 仅作为人工评审主文档。

---

## 1.1 机器可读 Schema 交付物

V1.15 冻结后建议同步维护以下文件，供后端校验、前端类型生成和接口测试使用：

```text
/docs/schema/AI_Travel_Planner_Data_Schema_V1.15.md
/schemas/common.definitions.schema.json
/schemas/travel-request.schema.json
/schemas/parse-travel-request-response.schema.json
/schemas/travel-plan-response.schema.json
/schemas/get-travel-plan-response.schema.json
/schemas/llm-recommendation-input.schema.json
/schemas/llm-recommendation-output.schema.json
/schemas/recalculate-request.schema.json
/schemas/recalculate-response.schema.json
/schemas/booking-redirect-request.schema.json
/schemas/booking-redirect-response.schema.json
/schemas/error-response.schema.json
/schemas/data-source-status.schema.json
/schemas/health-response.schema.json
```

生成规则：

1. Markdown 是人工评审源文件。
2. `/schemas/*.schema.json` 是自动化校验源文件。
3. 所有 `$ref` 必须能在机器可读文件中解析。
4. CI 应至少校验 JSON Schema 语法、示例数据合法性、关键业务语义校验用例。

---

## 2. 版本兼容策略

Schema 变更遵循以下策略：

1. 小版本升级优先使用 additive change。
2. 不允许删除 enum 旧值，只能新增值并要求前端具备 unknown fallback。
3. 不允许在兼容小版本中直接新增 required 字段；若必须新增 required 字段，提升 schema 主版本或提供默认值/迁移策略。
4. 所有 API 请求/响应必须带 `schema_version`。
5. App/Web 客户端必须忽略未知 enum 值，并展示降级文案。
6. 服务端必须支持至少一个前向兼容版本窗口。
7. V1.x 冻结前版本允许为了消除架构/Schema 不一致而进行 breaking change，但必须在 Changelog 和修复落实表中明确记录。
8. 一旦某版本被标记为“开发冻结版本”，后续再新增 required 字段、删除 enum、改变字段语义或改变推荐卡片数量，必须进入 V2.0 或提供迁移层。

---

## 3. 枚举定义

### 3.1 TransportMode

```json
[
  "RAIL",
  "FLIGHT",
  "TAXI",
  "SUBWAY",
  "BUS",
  "WALK",
  "RIDE_HAILING",
  "AIRPORT_TRANSFER",
  "RAIL_STATION_TRANSFER",
  "MIXED"
]
```

### 3.2 PlanType

```json
[
  "DIRECT_RAIL",
  "TRANSFER_RAIL",
  "MULTI_TRANSFER_RAIL",
  "RAIL_TICKET_ENHANCEMENT",
  "DIRECT_FLIGHT",
  "TRANSFER_FLIGHT",
  "MULTI_AIRPORT_FLIGHT",
  "FLIGHT_RAIL_MIXED",
  "GROUND_ONLY",
  "MIXED"
]
```

### 3.3 RiskLevel

```json
["LOW", "MEDIUM", "HIGH", "BLOCKED"]
```

### 3.4 PlanLifecycleStatus

```json
[
  "GENERATED",
  "PARTIALLY_VERIFIED",
  "VERIFIED",
  "EXPIRED",
  "INVALIDATED",
  "BOOKED"
]
```

### 3.5 PlanningStatus

业务规划结果状态。

```json
["PENDING", "RUNNING", "PARTIAL", "COMPLETE", "FAILED"]
```

### 3.6 JobStatus

异步任务状态。

```json
[
  "QUEUED",
  "RUNNING",
  "WAITING_SOURCE",
  "PARTIAL_READY",
  "COMPLETE",
  "FAILED",
  "CANCELLED"
]
```

### 3.7 RecommendationEligibility

```json
["ELIGIBLE", "NOT_RECOMMENDED", "BLOCKED"]
```

### 3.8 RecommendationType

```json
["CHEAPEST", "MOST_COMFORTABLE", "BALANCED"]
```

### 3.9 RecommendationSource

```json
["LLM", "DETERMINISTIC_FALLBACK", "RULE_BASED"]
```

### 3.10 TicketEnhancementGrade

```json
["S", "A", "NOT_RECOMMENDED", "BLOCKED"]
```

### 3.11 SourceFailureClass

```json
[
  "AUXILIARY_DATA_FAILURE",
  "FALLBACK_AVAILABLE_FAILURE",
  "CORE_FACT_FAILURE",
  "SAFETY_CRITICAL_FAILURE"
]
```

### 3.12 SourceFailureHandlingStrategy

```json
[
  "RETRY",
  "FALLBACK",
  "PARTIAL_RESULT",
  "DEGRADE_CONFIDENCE",
  "BLOCK_PLAN",
  "EXPLAIN_ONLY",
  "LOG_ONLY"
]
```

### 3.13 MissingComponentType

```json
[
  "RAIL_PRICE",
  "RAIL_AVAILABILITY",
  "RAIL_STOP_SEQUENCE",
  "FLIGHT_PRICE",
  "FLIGHT_STATUS",
  "PREVIOUS_FLIGHT",
  "REALTIME_TRAFFIC",
  "TAXI_ESTIMATE",
  "WEATHER",
  "TRANSFER_MINIMUM_TIME",
  "BOOKING_REDIRECT"
]
```

### 3.14 RecommendationSlotStatus

```json
["AVAILABLE", "NOT_AVAILABLE", "BLOCKED"]
```

---

## 4. 公共定义

### 4.1 Money

所有非差价金额必须使用 Money。`amount_minor` 使用最小货币单位，例如人民币分。

```json
{
  "type": "object",
  "required": ["amount_minor", "currency", "scale"],
  "additionalProperties": false,
  "properties": {
    "amount_minor": { "type": "integer", "minimum": 0 },
    "currency": { "type": "string", "minLength": 3, "maxLength": 3 },
    "scale": { "type": "integer", "minimum": 0, "default": 2 },
    "is_estimated": { "type": "boolean", "default": false },
    "display_text": { "type": ["string", "null"] }
  }
}
```

### 4.2 MoneyDelta

差价金额允许为负数，不能复用 Money。

```json
{
  "type": "object",
  "required": ["amount_minor", "currency", "scale"],
  "additionalProperties": false,
  "properties": {
    "amount_minor": { "type": "integer" },
    "currency": { "type": "string", "minLength": 3, "maxLength": 3 },
    "scale": { "type": "integer", "minimum": 0, "default": 2 },
    "display_text": { "type": ["string", "null"] }
  }
}
```

### 4.3 TimePoint

```json
{
  "type": "object",
  "required": ["datetime", "timezone"],
  "additionalProperties": false,
  "properties": {
    "datetime": { "type": "string", "format": "date-time" },
    "timezone": { "type": "string" },
    "source_timezone": { "type": ["string", "null"] }
  }
}
```

### 4.4 GeoPoint

```json
{
  "type": "object",
  "required": ["name"],
  "additionalProperties": false,
  "properties": {
    "name": { "type": "string" },
    "latitude": { "type": ["number", "null"] },
    "longitude": { "type": ["number", "null"] }
  }
}
```

### 4.5 NormalizedScores

```json
{
  "type": "object",
  "required": ["cost_score", "duration_score", "comfort_score", "risk_score", "overall_score"],
  "additionalProperties": false,
  "properties": {
    "cost_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "duration_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "comfort_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "risk_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "overall_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "score_version": { "type": ["string", "null"] }
  }
}
```

### 4.6 CacheMetadata

```json
{
  "type": "object",
  "required": ["cacheable", "cache_hit"],
  "additionalProperties": false,
  "properties": {
    "cacheable": { "type": "boolean" },
    "cache_hit": { "type": "boolean" },
    "cache_key": { "type": ["string", "null"] },
    "cache_ttl_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "cache_age_seconds": { "type": ["integer", "null"], "minimum": 0 }
  }
}
```

---

## 5. 数据源 Schema

### 5.1 DataSourceMetadata

```json
{
  "type": "object",
  "required": ["source_id", "source_name", "source_type", "authority_level", "license_status", "commercial_allowed", "cacheable", "fetched_at"],
  "additionalProperties": false,
  "properties": {
    "source_id": { "type": "string" },
    "source_name": { "type": "string" },
    "source_type": { "type": "string", "enum": ["MAP", "RAIL", "FLIGHT", "OTA", "TAXI", "LLM", "INTERNAL_CALCULATION"] },
    "authority_level": { "type": "string", "enum": ["S", "A", "B", "C"] },
    "source_priority": { "type": ["integer", "null"], "minimum": 0 },
    "source_region": { "type": ["string", "null"] },
    "api_version": { "type": ["string", "null"] },
    "fetched_at": { "$ref": "#/definitions/TimePoint" },
    "data_freshness_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "license_status": { "type": "string", "enum": ["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"] },
    "commercial_allowed": { "type": "boolean" },
    "cacheable": { "type": "boolean" },
    "cache_ttl_seconds": { "type": ["integer", "null"], "minimum": 0 },
    "sla_level": { "type": ["string", "null"] },
    "cache_metadata": { "$ref": "#/definitions/CacheMetadata" }
  }
}
```

### 5.2 DataSourceConfig

生产环境数据源白名单配置契约。

```json
{
  "type": "object",
  "required": [
    "source_id",
    "source_name",
    "source_type",
    "authority_level",
    "license_status",
    "commercial_allowed",
    "update_frequency",
    "sla_level",
    "qps_limit",
    "fallback_source_id",
    "enabled",
    "environment"
  ],
  "additionalProperties": false,
  "properties": {
    "source_id": { "type": "string" },
    "source_name": { "type": "string" },
    "source_type": { "type": "string", "enum": ["MAP", "RAIL", "FLIGHT", "OTA", "TAXI", "LLM", "INTERNAL_CALCULATION"] },
    "authority_level": { "type": "string", "enum": ["S", "A", "B", "C"] },
    "license_status": { "type": "string", "enum": ["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"] },
    "commercial_allowed": { "type": "boolean" },
    "update_frequency": { "type": "string" },
    "sla_level": { "type": "string" },
    "qps_limit": { "type": "integer", "minimum": 0 },
    "fallback_source_id": { "type": ["string", "null"] },
    "enabled": { "type": "boolean" },
    "environment": { "type": "string", "enum": ["DEV", "TEST", "PROD"] },
    "cache_strategy_id": { "type": ["string", "null"] },
    "last_checked_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] }
  }
}
```

### 5.3 SourceFailure

字段命名以 Schema 为准。系统架构文档中的 `failure_type` 对应本 Schema 的 `failure_class`，`error_message` 对应本 Schema 的 `message`。后续架构文档、日志实现和监控字段应统一使用 `failure_class` 与 `message`。V1.15 起，SourceFailure 必须保留 `trace_id`、`correlation_id`、`source_used_id` 与 `fallback_reason`，用于串联 API 响应、日志、监控告警和 fallback 审计。

```json
{
  "type": "object",
  "required": [
    "failure_id",
    "request_id",
    "correlation_id",
    "trace_id",
    "source_id",
    "adapter_name",
    "failure_class",
    "handling_strategy",
    "error_code",
    "message",
    "retry_count",
    "fallback_used",
    "fallback_source_id",
    "fallback_reason",
    "source_used_id",
    "final_handling_strategy",
    "impacted_plan_types",
    "occurred_at"
  ],
  "additionalProperties": false,
  "properties": {
    "failure_id": {
      "type": "string"
    },
    "request_id": {
      "type": "string"
    },
    "source_id": {
      "type": "string"
    },
    "adapter_name": {
      "type": "string"
    },
    "failure_class": {
      "type": "string",
      "enum": [
        "AUXILIARY_DATA_FAILURE",
        "FALLBACK_AVAILABLE_FAILURE",
        "CORE_FACT_FAILURE",
        "SAFETY_CRITICAL_FAILURE"
      ]
    },
    "handling_strategy": {
      "type": "string",
      "enum": [
        "RETRY",
        "FALLBACK",
        "PARTIAL_RESULT",
        "DEGRADE_CONFIDENCE",
        "BLOCK_PLAN",
        "EXPLAIN_ONLY",
        "LOG_ONLY"
      ]
    },
    "error_code": {
      "type": [
        "string",
        "null"
      ]
    },
    "message": {
      "type": "string"
    },
    "retry_count": {
      "type": "integer",
      "minimum": 0
    },
    "fallback_used": {
      "type": "boolean"
    },
    "fallback_source_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "final_handling_strategy": {
      "type": "string",
      "enum": [
        "RETRY",
        "FALLBACK",
        "PARTIAL_RESULT",
        "DEGRADE_CONFIDENCE",
        "BLOCK_PLAN",
        "EXPLAIN_ONLY",
        "LOG_ONLY"
      ]
    },
    "impacted_plan_types": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "DIRECT_RAIL",
          "TRANSFER_RAIL",
          "MULTI_TRANSFER_RAIL",
          "RAIL_TICKET_ENHANCEMENT",
          "DIRECT_FLIGHT",
          "TRANSFER_FLIGHT",
          "MULTI_AIRPORT_FLIGHT",
          "FLIGHT_RAIL_MIXED",
          "GROUND_ONLY",
          "MIXED"
        ]
      }
    },
    "occurred_at": {
      "$ref": "#/definitions/TimePoint"
    },
    "user_visible_message": {
      "type": [
        "string",
        "null"
      ]
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "source_used_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "fallback_reason": {
      "type": [
        "string",
        "null"
      ]
    }
  }
}
```


SourceFailure 语义规则：

| 规则 ID | 规则 |
|---|---|
| SF-001 | `request_id`、`trace_id`、`correlation_id` 必须与触发本次数据源调用的 API 请求链路保持一致；若上游未传入 trace/correlation，应由后端生成后写入。 |
| SF-002 | 当 `fallback_used = true` 时，`fallback_source_id`、`source_used_id` 与 `fallback_reason` 必须非空；`source_id` 表示失败的原始数据源，`source_used_id` 表示最终采用的数据源。 |
| SF-003 | 当 `fallback_used = false` 时，`source_used_id` 可以为 null；若最终仍使用原数据源的部分数据，应填原 `source_id`。 |
| SF-004 | `final_handling_strategy = BLOCK_PLAN` 时，`impacted_plan_types` 不得为空。 |

### 5.4 DataSourceRuntimeStatus

用于 `/api/data-sources/status` 返回运行时状态。该对象只暴露运行健康度、最近成功/失败、延迟和降级原因，不直接暴露生产配置细节，避免把 DataSourceConfig 当作运行状态接口返回。

```json
{
  "type": "object",
  "required": ["source_id", "source_name", "source_type", "enabled", "health_status", "checked_at"],
  "additionalProperties": false,
  "properties": {
    "source_id": { "type": "string" },
    "source_name": { "type": "string" },
    "source_type": { "type": "string", "enum": ["MAP", "RAIL", "FLIGHT", "OTA", "TAXI", "LLM", "INTERNAL_CALCULATION"] },
    "enabled": { "type": "boolean" },
    "health_status": { "type": "string", "enum": ["OK", "DEGRADED", "DOWN", "DISABLED"] },
    "authority_level": { "type": ["string", "null"], "enum": ["S", "A", "B", "C", null] },
    "license_status": { "type": ["string", "null"], "enum": ["APPROVED", "PENDING_REVIEW", "NOT_APPROVED", null] },
    "commercial_allowed": { "type": ["boolean", "null"] },
    "last_success_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "last_failure_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "latest_failure": { "oneOf": [{ "$ref": "#/definitions/SourceFailure" }, { "type": "null" }] },
    "average_latency_ms": { "type": ["integer", "null"], "minimum": 0 },
    "degraded_reason": { "type": ["string", "null"] },
    "checked_at": { "$ref": "#/definitions/TimePoint" }
  }
}
```

DataSourceRuntimeStatus 语义规则：

| 规则 ID | 规则 |
|---|---|
| DS-001 | `health_status = DISABLED` 时，`enabled` 必须为 `false`。 |
| DS-002 | `health_status = DOWN` 或 `DEGRADED` 时，建议提供 `latest_failure` 或 `degraded_reason`。 |
| DS-003 | 状态接口不得返回第三方密钥、内部限流策略细节、账号、token 或未脱敏错误堆栈。 |
| DS-004 | 所有进入 `TravelPlan.data_sources`、segment.data_source、CostBreakdown.items[*].data_source 的 `DataSourceMetadata` 必须保留 `authority_level`、`license_status`、`commercial_allowed` 与 `cacheable`，便于前端展示数据来源和后端审计。 |

---

## 6. 请求与候选对象

### 6.1 TravelHardConstraints

用于承载用户明确提出的硬约束。硬约束应由后端严格执行，不满足时应过滤方案或进入 blocked/missing explanation。

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "max_transfer_count": { "type": ["integer", "null"], "minimum": 0 },
    "latest_arrival_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "earliest_departure_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "max_total_duration_minutes": { "type": ["integer", "null"], "minimum": 0 },
    "max_total_cost": { "oneOf": [{ "$ref": "#/definitions/Money" }, { "type": "null" }] },
    "max_walking_distance_meters": { "type": ["integer", "null"], "minimum": 0 },
    "must_have_available_ticket": { "type": ["boolean", "null"] },
    "exclude_red_eye_flight": { "type": ["boolean", "null"] },
    "exclude_high_risk_transfer": { "type": ["boolean", "null"] },
    "exclude_ticket_enhancement": { "type": ["boolean", "null"] }
  }
}
```

### 6.2 TravelSoftPreferences

用于承载用户偏好。软偏好影响排序、评分和推荐解释，但原则上不直接阻断方案。

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "prefer_low_cost": { "type": ["boolean", "null"] },
    "prefer_short_duration": { "type": ["boolean", "null"] },
    "prefer_less_transfer": { "type": ["boolean", "null"] },
    "prefer_rail": { "type": ["boolean", "null"] },
    "prefer_flight": { "type": ["boolean", "null"] },
    "prefer_daytime_departure": { "type": ["boolean", "null"] },
    "prefer_low_walking_distance": { "type": ["boolean", "null"] },
    "prefer_luggage_friendly": { "type": ["boolean", "null"] },
    "comfort_priority_weight": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
    "cost_priority_weight": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
    "duration_priority_weight": { "type": ["number", "null"], "minimum": 0, "maximum": 1 }
  }
}
```

### 6.3 TravelRequest

```json
{
  "type": "object",
  "required": ["schema_version", "request_id", "raw_user_input", "origin_text", "destination_text", "travel_date", "preferences", "hard_constraints", "soft_preferences"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "request_id": { "type": "string" },
    "trace_id": { "type": "string" },
    "correlation_id": { "type": "string" },
    "idempotency_key": { "type": ["string", "null"] },
    "raw_user_input": { "type": "string" },
    "origin_text": { "type": "string" },
    "destination_text": { "type": "string" },
    "travel_date": { "type": "string", "format": "date" },
    "earliest_departure_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "latest_arrival_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "preferred_departure_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "preferences": { "type": "array", "items": { "type": "string", "enum": ["CHEAPEST", "MOST_COMFORTABLE", "BALANCED"] }, "minItems": 1 },
    "preference_source": { "type": "string", "enum": ["USER_EXPLICIT", "SYSTEM_DEFAULT"], "default": "SYSTEM_DEFAULT" },
    "allowed_transport_modes": { "type": "array", "items": { "type": "string", "enum": ["RAIL", "FLIGHT", "TAXI", "SUBWAY", "BUS", "WALK", "RIDE_HAILING", "AIRPORT_TRANSFER", "RAIL_STATION_TRANSFER", "MIXED"] } },
    "excluded_transport_modes": { "type": "array", "items": { "type": "string", "enum": ["RAIL", "FLIGHT", "TAXI", "SUBWAY", "BUS", "WALK", "RIDE_HAILING", "AIRPORT_TRANSFER", "RAIL_STATION_TRANSFER", "MIXED"] } },
    "rail_transfer_allowed": { "type": "boolean", "default": true },
    "flight_transfer_allowed": { "type": "boolean", "default": true },
    "mixed_transport_allowed": { "type": "boolean", "default": true },
    "ticket_enhancement_allowed": { "type": "boolean", "default": true },
    "high_risk_plan_allowed": { "type": "boolean", "default": false },
    "hard_constraints": { "$ref": "#/definitions/TravelHardConstraints" },
    "soft_preferences": { "$ref": "#/definitions/TravelSoftPreferences" }
  }
}
```

### 6.4 StationCandidate

```json
{
  "type": "object",
  "required": ["station_id", "station_name", "city", "distance_from_location_meters", "estimated_transfer_minutes", "priority_score", "data_source"],
  "additionalProperties": false,
  "properties": {
    "station_id": { "type": "string" },
    "station_code": { "type": ["string", "null"] },
    "station_name": { "type": "string" },
    "city": { "type": "string" },
    "latitude": { "type": ["number", "null"] },
    "longitude": { "type": ["number", "null"] },
    "distance_from_location_meters": { "type": "integer", "minimum": 0 },
    "estimated_transfer_minutes": { "type": "integer", "minimum": 0 },
    "estimated_transfer_cost": { "oneOf": [{ "$ref": "#/definitions/Money" }, { "type": "null" }] },
    "is_major_hub": { "type": "boolean" },
    "priority_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "ranking_reasons": { "type": "array", "items": { "type": "string" } },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

### 6.5 AirportCandidate

```json
{
  "type": "object",
  "required": ["airport_id", "airport_name", "city", "distance_from_location_meters", "estimated_transfer_minutes", "priority_score", "data_source"],
  "additionalProperties": false,
  "properties": {
    "airport_id": { "type": "string" },
    "airport_name": { "type": "string" },
    "iata_code": { "type": ["string", "null"] },
    "icao_code": { "type": ["string", "null"] },
    "city": { "type": "string" },
    "latitude": { "type": ["number", "null"] },
    "longitude": { "type": ["number", "null"] },
    "distance_from_location_meters": { "type": "integer", "minimum": 0 },
    "estimated_transfer_minutes": { "type": "integer", "minimum": 0 },
    "estimated_transfer_cost": { "oneOf": [{ "$ref": "#/definitions/Money" }, { "type": "null" }] },
    "is_major_hub": { "type": "boolean" },
    "airport_complexity_score": { "type": "number", "minimum": 0, "maximum": 10 },
    "priority_score": { "type": "number", "minimum": 0, "maximum": 100 },
    "ranking_reasons": { "type": "array", "items": { "type": "string" } },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

---

## 7. Segment Schema

### 7.1 SeatOption

```json
{
  "type": "object",
  "required": ["option_id", "option_version", "seat_type", "price", "available", "data_source"],
  "additionalProperties": false,
  "properties": {
    "option_id": { "type": "string" },
    "option_version": { "type": "string" },
    "seat_type": { "type": "string", "enum": ["SECOND_CLASS", "FIRST_CLASS", "BUSINESS_CLASS"] },
    "display_name": { "type": "string" },
    "price": { "$ref": "#/definitions/Money" },
    "available": { "type": "boolean" },
    "remaining_count": { "type": ["integer", "null"], "minimum": 0 },
    "comfort_delta": { "type": "number", "minimum": -10, "maximum": 10 },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

### 7.2 CabinOption

```json
{
  "type": "object",
  "required": ["option_id", "option_version", "cabin_type", "price", "available", "data_source"],
  "additionalProperties": false,
  "properties": {
    "option_id": { "type": "string" },
    "option_version": { "type": "string" },
    "cabin_type": { "type": "string", "enum": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"] },
    "display_name": { "type": "string" },
    "price": { "$ref": "#/definitions/Money" },
    "available": { "type": "boolean" },
    "remaining_count": { "type": ["integer", "null"], "minimum": 0 },
    "comfort_delta": { "type": "number", "minimum": -10, "maximum": 10 },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

### 7.3 RailSegment

```json
{
  "type": "object",
  "required": ["segment_id", "segment_type", "train_no", "origin_station", "destination_station", "departure_time", "arrival_time", "duration_minutes", "seat_options", "selected_seat_type", "selected_seat_option_id", "risk_level", "data_source"],
  "additionalProperties": false,
  "properties": {
    "segment_id": { "type": "string" },
    "segment_type": { "const": "RAIL" },
    "train_no": { "type": "string" },
    "origin_station": { "$ref": "#/definitions/StationCandidate" },
    "destination_station": { "$ref": "#/definitions/StationCandidate" },
    "departure_time": { "$ref": "#/definitions/TimePoint" },
    "arrival_time": { "$ref": "#/definitions/TimePoint" },
    "duration_minutes": { "type": "integer", "minimum": 0 },
    "seat_options": { "type": "array", "minItems": 1, "items": { "$ref": "#/definitions/SeatOption" } },
    "selected_seat_type": { "type": "string", "enum": ["SECOND_CLASS", "FIRST_CLASS", "BUSINESS_CLASS"] },
    "selected_seat_option_id": { "type": "string" },
    "stop_sequence": { "type": "array", "items": { "type": "string" } },
    "ticket_enhancement": { "$ref": "#/definitions/TicketEnhancement" },
    "normalized_scores": { "$ref": "#/definitions/NormalizedScores" },
    "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

### 7.4 FlightSegment

```json
{
  "type": "object",
  "required": ["segment_id", "segment_type", "flight_no", "origin_airport", "destination_airport", "departure_time", "arrival_time", "duration_minutes", "cabin_options", "selected_cabin_type", "selected_cabin_option_id", "risk_level", "data_source"],
  "additionalProperties": false,
  "properties": {
    "segment_id": { "type": "string" },
    "segment_type": { "const": "FLIGHT" },
    "flight_no": { "type": "string" },
    "airline_name": { "type": "string" },
    "airline_code": { "type": ["string", "null"] },
    "origin_airport": { "$ref": "#/definitions/AirportCandidate" },
    "destination_airport": { "$ref": "#/definitions/AirportCandidate" },
    "departure_time": { "$ref": "#/definitions/TimePoint" },
    "arrival_time": { "$ref": "#/definitions/TimePoint" },
    "duration_minutes": { "type": "integer", "minimum": 0 },
    "cabin_options": { "type": "array", "minItems": 1, "items": { "$ref": "#/definitions/CabinOption" } },
    "selected_cabin_type": { "type": "string", "enum": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"] },
    "selected_cabin_option_id": { "type": "string" },
    "delay_risk_score": { "type": ["number", "null"], "minimum": 0, "maximum": 10 },
    "previous_flight_risk_available": { "type": "boolean" },
    "normalized_scores": { "$ref": "#/definitions/NormalizedScores" },
    "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

### 7.5 LocalTransferSegment

字段与系统架构输出对齐：`origin`、`destination`、`transfer_mode`、`distance_meters`、`duration_minutes`、`estimated_cost`、`traffic_risk`、`walking_distance_meters`、`data_source`、`redirect_info`。

```json
{
  "type": "object",
  "required": ["segment_id", "segment_type", "transfer_mode", "origin", "destination", "duration_minutes", "distance_meters", "estimated_cost", "risk_level", "data_source"],
  "additionalProperties": false,
  "properties": {
    "segment_id": { "type": "string" },
    "segment_type": { "const": "LOCAL_TRANSFER" },
    "transfer_mode": { "type": "string", "enum": ["TAXI", "SUBWAY", "BUS", "WALK", "RIDE_HAILING", "AIRPORT_TRANSFER", "RAIL_STATION_TRANSFER"] },
    "origin": { "$ref": "#/definitions/GeoPoint" },
    "destination": { "$ref": "#/definitions/GeoPoint" },
    "duration_minutes": { "type": "integer", "minimum": 0 },
    "distance_meters": { "type": "integer", "minimum": 0 },
    "estimated_cost": { "$ref": "#/definitions/Money" },
    "walking_distance_meters": { "type": ["integer", "null"], "minimum": 0 },
    "traffic_risk": { "type": ["number", "null"], "minimum": 0, "maximum": 10 },
    "redirect_info": { "oneOf": [{ "$ref": "#/definitions/BookingRedirect" }, { "type": "null" }] },
    "normalized_scores": { "$ref": "#/definitions/NormalizedScores" },
    "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

---

Segment 与数据源语义规则：

| 规则 ID | 规则 |
|---|---|
| SEG-001 | `RailSegment.selected_seat_option_id` 必须存在于同一 segment 的 `seat_options[*].option_id` 中。 |
| SEG-002 | `RailSegment.selected_seat_type` 必须等于所选 `SeatOption.seat_type`。 |
| SEG-003 | `FlightSegment.selected_cabin_option_id` 必须存在于同一 segment 的 `cabin_options[*].option_id` 中。 |
| SEG-004 | `FlightSegment.selected_cabin_type` 必须等于所选 `CabinOption.cabin_type`。 |
| SEG-005 | `seat_options` 与 `cabin_options` 不得为空；若数据源无法返回可选座席/舱位，则对应主交通方案不得进入可选候选池，应进入缺失说明或降级路径。 |
| SEG-006 | 所有进入用户可见方案的站点、机场、交通分段、座席/舱位选项、费用明细必须输出 `DataSourceMetadata`；内部计算结果应使用 `source_type = INTERNAL_CALCULATION` 的数据源元信息。 |

---

## 8. 票源增强 Schema

### 8.1 TicketEnhancement

```json
{
  "type": "object",
  "required": ["enabled", "enhancement_type", "actual_origin_station", "actual_destination_station", "ticket_origin_station", "ticket_destination_station", "ticket_covers_actual_route", "requires_onboard_supplement", "grade", "risk_level"],
  "additionalProperties": false,
  "properties": {
    "enabled": { "type": "boolean" },
    "enhancement_type": { "type": "string", "enum": ["NONE", "PRE_ORIGIN_EXTENSION", "POST_DESTINATION_EXTENSION", "BOTH_SIDE_EXTENSION", "SHORT_BUY_LONG_RIDE", "BLOCKED_NOT_COVERED"] },
    "actual_origin_station": { "type": "string" },
    "actual_destination_station": { "type": "string" },
    "ticket_origin_station": { "type": "string" },
    "ticket_destination_station": { "type": "string" },
    "ticket_covers_actual_route": { "type": "boolean" },
    "requires_onboard_supplement": { "type": "boolean" },
    "pre_origin_extra_stop_count": { "type": "integer", "minimum": 0 },
    "post_destination_extra_stop_count": { "type": "integer", "minimum": 0 },
    "unused_distance_ratio": { "type": "number", "minimum": 0 },
    "extra_cost": { "$ref": "#/definitions/Money" },
    "extra_cost_ratio": { "type": "number", "minimum": 0 },
    "coverage_validation": {
      "type": "object",
      "required": ["validated"],
      "additionalProperties": false,
      "properties": {
        "actual_origin_index": { "type": ["integer", "null"] },
        "actual_destination_index": { "type": ["integer", "null"] },
        "ticket_origin_index": { "type": ["integer", "null"] },
        "ticket_destination_index": { "type": ["integer", "null"] },
        "validated": { "type": "boolean" },
        "validation_message": { "type": ["string", "null"] },
        "validation_source": { "type": ["string", "null"] },
        "validation_rule_version": { "type": ["string", "null"] },
        "railway_policy_reference": { "type": ["string", "null"] }
      }
    },
    "benefit_types": { "type": "array", "items": { "type": "string" } },
    "grade": { "type": "string", "enum": ["S", "A", "NOT_RECOMMENDED", "BLOCKED"] },
    "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "recommendation_allowed": { "type": "boolean" },
    "reason": { "type": "string" },
    "warning_message": { "type": "string" }
  }
}
```

---

## 9. 方案、评分与推荐

### 9.1 CostBreakdown

```json
{
  "type": "object",
  "required": ["total_cost", "items"],
  "additionalProperties": false,
  "properties": {
    "total_cost": { "$ref": "#/definitions/Money" },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["item_id", "item_type", "name", "amount", "data_source"],
        "additionalProperties": false,
        "properties": {
          "item_id": { "type": "string" },
          "item_type": { "type": "string", "enum": ["LOCAL_TRANSFER", "RAIL", "FLIGHT", "TICKET_ENHANCEMENT_EXTRA", "SERVICE_FEE", "OTHER"] },
          "name": { "type": "string" },
          "amount": { "$ref": "#/definitions/Money" },
          "segment_id": { "type": ["string", "null"] },
          "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
        }
      }
    },
    "price_confidence": { "type": "string", "enum": ["HIGH", "MEDIUM", "LOW"] },
    "price_warning": { "type": ["string", "null"] }
  }
}
```

### 9.2 ComfortScore

```json
{
  "type": "object",
  "required": ["total_score", "confidence_level", "breakdown"],
  "additionalProperties": false,
  "properties": {
    "total_score": { "type": "number", "minimum": 0, "maximum": 10 },
    "confidence_level": { "type": "string", "enum": ["HIGH", "MEDIUM", "LOW"] },
    "breakdown": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "transfer_complexity": { "type": "number", "minimum": 0, "maximum": 10 },
        "waiting_pressure": { "type": "number", "minimum": 0, "maximum": 10 },
        "time_friendliness": { "type": "number", "minimum": 0, "maximum": 10 },
        "seat_or_cabin_comfort": { "type": "number", "minimum": 0, "maximum": 10 },
        "local_transfer_convenience": { "type": "number", "minimum": 0, "maximum": 10 },
        "missed_connection_risk": { "type": "number", "minimum": 0, "maximum": 10 },
        "weather_or_traffic_impact": { "type": "number", "minimum": 0, "maximum": 10 },
        "luggage_friendliness": { "type": "number", "minimum": 0, "maximum": 10 }
      }
    },
    "score_vector": { "$ref": "#/definitions/NormalizedScores" },
    "explanation": { "type": "string" },
    "missing_data_impact": { "type": ["string", "null"] }
  }
}
```

### 9.3 RiskItem

风险项必须结构化，便于前端稳定展示风险标签、后端执行 BLOCKED 规则、自动化测试断言风险原因。

```json
{
  "type": "object",
  "required": ["risk_id", "risk_type", "risk_level", "message", "blocking", "affected_segment_ids"],
  "additionalProperties": false,
  "properties": {
    "risk_id": { "type": "string" },
    "risk_type": {
      "type": "string",
      "enum": [
        "RAIL_TRANSFER_RISK",
        "FLIGHT_TRANSFER_RISK",
        "CROSS_STATION_TRANSFER",
        "CROSS_TERMINAL_TRANSFER",
        "BAGGAGE_RECHECK",
        "TICKET_ENHANCEMENT_RISK",
        "SHORT_BUY_LONG_RIDE_RISK",
        "TRAFFIC_RISK",
        "DELAY_RISK",
        "DATA_INCOMPLETE_RISK"
      ]
    },
    "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "message": { "type": "string" },
    "blocking": { "type": "boolean" },
    "affected_segment_ids": { "type": "array", "items": { "type": "string" } },
    "mitigation": { "type": ["string", "null"] },
    "data_source": { "oneOf": [{ "$ref": "#/definitions/DataSourceMetadata" }, { "type": "null" }] }
  }
}
```

### 9.4 RiskAssessment

```json
{
  "type": "object",
  "required": ["overall_risk_level", "risk_items", "recommendation_allowed"],
  "additionalProperties": false,
  "properties": {
    "overall_risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "BLOCKED"] },
    "risk_items": { "type": "array", "items": { "$ref": "#/definitions/RiskItem" } },
    "recommendation_allowed": { "type": "boolean" }
  }
}
```

### 9.5 DataQuality

```json
{
  "type": "object",
  "required": ["overall_confidence", "missing_data_types", "affected_modules"],
  "additionalProperties": false,
  "properties": {
    "overall_confidence": { "type": "string", "enum": ["HIGH", "MEDIUM", "LOW"] },
    "missing_data_types": { "type": "array", "items": { "type": "string", "enum": ["RAIL_PRICE", "RAIL_AVAILABILITY", "RAIL_STOP_SEQUENCE", "FLIGHT_PRICE", "FLIGHT_STATUS", "PREVIOUS_FLIGHT", "REALTIME_TRAFFIC", "TAXI_ESTIMATE", "WEATHER", "TRANSFER_MINIMUM_TIME", "BOOKING_REDIRECT"] } },
    "affected_modules": { "type": "array", "items": { "type": "string", "enum": ["COST_CALCULATION", "COMFORT_SCORE", "RISK_ASSESSMENT", "RECOMMENDATION", "REDIRECT"] } },
    "user_visible_message": { "type": ["string", "null"] }
  }
}
```

### 9.6 TravelPlan

```json
{
  "type": "object",
  "required": ["schema_version", "plan_id", "plan_type", "plan_lifecycle_status", "recommendation_eligibility", "can_be_selected_by_llm", "segments", "total_duration_minutes", "cost_breakdown", "comfort_score", "risk_assessment", "data_sources"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "plan_id": { "type": "string" },
    "plan_type": { "type": "string", "enum": ["DIRECT_RAIL", "TRANSFER_RAIL", "MULTI_TRANSFER_RAIL", "RAIL_TICKET_ENHANCEMENT", "DIRECT_FLIGHT", "TRANSFER_FLIGHT", "MULTI_AIRPORT_FLIGHT", "FLIGHT_RAIL_MIXED", "GROUND_ONLY", "MIXED"] },
    "plan_lifecycle_status": { "type": "string", "enum": ["GENERATED", "PARTIALLY_VERIFIED", "VERIFIED", "EXPIRED", "INVALIDATED", "BOOKED"] },
    "last_verified_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "expires_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "recommendation_eligibility": { "type": "string", "enum": ["ELIGIBLE", "NOT_RECOMMENDED", "BLOCKED"] },
    "block_reason_code": { "type": ["string", "null"] },
    "block_reason_message": { "type": ["string", "null"] },
    "can_be_selected_by_llm": { "type": "boolean" },
    "display_name": { "type": "string" },
    "segments": { "type": "array", "minItems": 1, "items": { "oneOf": [{ "$ref": "#/definitions/RailSegment" }, { "$ref": "#/definitions/FlightSegment" }, { "$ref": "#/definitions/LocalTransferSegment" }] } },
    "departure_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "arrival_time": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "total_duration_minutes": { "type": "integer", "minimum": 0 },
    "total_waiting_minutes": { "type": "integer", "minimum": 0 },
    "transfer_count": { "type": "integer", "minimum": 0 },
    "cost_breakdown": { "$ref": "#/definitions/CostBreakdown" },
    "comfort_score": { "$ref": "#/definitions/ComfortScore" },
    "risk_assessment": { "$ref": "#/definitions/RiskAssessment" },
    "data_quality": { "$ref": "#/definitions/DataQuality" },
    "data_sources": { "type": "array", "minItems": 1, "items": { "$ref": "#/definitions/DataSourceMetadata" } },
    "booking_redirects": { "type": "array", "items": { "$ref": "#/definitions/BookingRedirect" } }
  }
}
```

---

## 10. LLM 推荐 Schema

### 10.1 LLMRecommendationInput

```json
{
  "type": "object",
  "required": ["schema_version", "request_id", "travel_request", "candidate_plan_ids", "candidate_plans"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "request_id": { "type": "string" },
    "travel_request": { "$ref": "#/definitions/TravelRequest" },
    "candidate_plan_ids": { "type": "array", "items": { "type": "string" }, "minItems": 1, "maxItems": 15 },
    "candidate_plans": { "type": "array", "items": { "$ref": "#/definitions/TravelPlan" }, "minItems": 1, "maxItems": 15 },
    "selection_constraints": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "exclude_high_risk": { "type": "boolean", "default": true },
        "exclude_blocked": { "type": "boolean", "default": true },
        "require_can_be_selected_by_llm": { "type": "boolean", "default": true }
      }
    }
  }
}
```

### 10.2 LLMRecommendationOutput

LLM 不得输出 `candidate_plan_ids`。候选池 ID 只来自系统输入。V1.15 使用三卡位状态模型，三类推荐必须各返回一个 slot；无可用方案时返回 `NOT_AVAILABLE` 或 `BLOCKED`，不得省略卡位。

```json
{
  "type": "object",
  "required": ["schema_version", "selected_recommendations", "validation_blockers", "explanation"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "selected_recommendations": {
      "type": "array",
      "minItems": 3,
      "maxItems": 3,
      "items": { "$ref": "#/definitions/RecommendationSlot" }
    },
    "validation_blockers": { "type": "array", "items": { "type": "string" } },
    "explanation": { "type": "string" }
  }
}
```

三卡位业务规则：

1. selected_recommendations 必须且仅能包含 CHEAPEST、MOST_COMFORTABLE、BALANCED 各一个。
2. status = AVAILABLE 时，plan_id 必须非 null，且必须属于 input.candidate_plan_ids。
3. status = NOT_AVAILABLE 或 BLOCKED 时，plan_id 必须为 null，reason 必须说明原因。
4. LLM 不得通过省略推荐项表达“无推荐”。

后端必须额外进行业务语义校验。以下规则必须进入 Semantic Validator 与单元测试：

| 规则 ID | 规则 |
|---|---|
| REC-001 | `selected_recommendations.length == 3`。 |
| REC-002 | `recommendation_type` 集合必须等于 `{CHEAPEST, MOST_COMFORTABLE, BALANCED}`，不得重复、不得缺失。 |
| REC-003 | `status = AVAILABLE` 时，`plan_id != null`。 |
| REC-004 | `status = NOT_AVAILABLE` 或 `BLOCKED` 时，`plan_id == null` 且 `reason` 非空。 |
| REC-005 | `status = AVAILABLE` 的 `plan_id` 必须属于 `input.candidate_plan_ids`。 |
| REC-006 | `status = AVAILABLE` 的 selected plan 必须满足 `can_be_selected_by_llm == true`。 |
| REC-007 | `status = AVAILABLE` 的 selected plan 必须满足 `recommendation_eligibility != BLOCKED`。 |
| REC-008 | LLM 不得修改价格、时间、车次、航班、余票、数据源等事实字段。 |
| REC-009 | `candidate_plan_ids` 与 `candidate_plans[*].plan_id` 集合必须完全一致。 |
| REC-010 | LLM 输入候选池不得超过 15 个方案；超过时必须先由确定性排序模块裁剪。 |
| REC-011 | 正常 COMPLETE 推荐路径进入 LLM 前的候选池目标区间为 5–15 个方案；若确定性候选不足 5 个，允许以 1–4 个候选进入降级推荐，但必须在 `LLMValidationResult.invalid_reasons` 或推荐说明中记录候选不足原因。 |
| REC-012 | `candidate_plan_ids` 顺序应与传入 LLM 的候选展示顺序一致，便于 LLM 推荐解释和后端审计复现。 |

---

## 11. API 响应 Schema

### 11.1 ParseTravelRequestResponse

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "travel_request",
    "llm_validation_result",
    "generated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "travel_request": {
      "$ref": "#/definitions/TravelRequest"
    },
    "llm_validation_result": {
      "$ref": "#/definitions/LLMValidationResult"
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

### 11.2 GetTravelPlanResponse

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "plan",
    "generated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "plan": {
      "$ref": "#/definitions/TravelPlan"
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

### 11.3 DataSourceStatusResponse

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "sources",
    "generated_at",
    "request_id"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "sources": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/DataSourceRuntimeStatus"
      }
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

说明：`DataSourceConfig` 是配置契约，不应直接作为 `/api/data-sources/status` 的响应对象；状态接口应返回 `DataSourceRuntimeStatus`。

### 11.4 HealthResponse

```json
{
  "type": "object",
  "required": ["schema_version", "status", "service_name", "version", "checked_at"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "status": { "type": "string", "enum": ["OK", "DEGRADED", "DOWN"] },
    "service_name": { "type": "string" },
    "version": { "type": "string" },
    "checked_at": { "$ref": "#/definitions/TimePoint" }
  }
}
```

HealthResponse 也属于 API 响应，必须带 `schema_version`。


### 11.5 ErrorResponse

统一错误返回对象，适用于参数错误、无可用方案、数据源不可用、LLM 输出非法且降级失败等场景。业务 API 可根据 HTTP 状态码返回该对象。

V1.15 起，`retryable` 与 `details` 必须出现在错误响应中，避免前端和测试用例在错误路径上出现分支歧义；`details` 允许为 `null`，也允许作为唯一诊断扩展对象。

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "error_code",
    "message",
    "user_visible_message",
    "retryable",
    "details",
    "generated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "error_code": {
      "type": "string"
    },
    "message": {
      "type": "string"
    },
    "user_visible_message": {
      "type": "string"
    },
    "retryable": {
      "type": "boolean"
    },
    "details": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": true
        },
        {
          "type": "null"
        }
      ]
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```


### 11.5.1 API 错误响应复用规则

API 响应统一规则：

| 规则 ID | 规则 |
|---|---|
| API-001 | 所有业务 API 成功响应必须包含 `schema_version`，包括 `/api/health`。 |
| API-002 | 所有 4xx / 5xx 错误响应必须复用 `ErrorResponse`。 |
| API-003 | 同一个请求链路中的 `request_id`、`trace_id`、`correlation_id` 应在响应、日志、SourceFailure 中保持可关联。 |
| API-004 | `details` 是唯一允许扩展的错误诊断字段；不得在 ErrorResponse 顶层临时新增未定义字段。 |
| API-005 | 除 `/api/health` 外，业务成功响应应至少暴露 `request_id`；当请求或服务端生成了 `trace_id`、`correlation_id`、`idempotency_key` 时，响应必须原样透传或返回服务端生成值。 |
| API-006 | `BookingRedirectResponse` 必须包含顶层 `generated_at`，用于表示本次响应封装时间；具体第三方链接生成时间仍以 `BookingRedirect.generated_at` 为准。 |
| API-007 | 任何写入日志、监控或 `SourceFailure` 的失败事件，必须带可关联的 `request_id`、`trace_id`、`correlation_id`；数据源 fallback 场景必须记录失败源、最终使用源和 fallback 原因。 |


所有 API 的 4xx / 5xx 错误响应必须复用 `ErrorResponse`，不得返回临时结构，例如 `{ "error": "xxx" }` 或 `{ "message": "xxx" }`。

适用接口包括：

1. `POST /api/travel/parse`
2. `POST /api/travel/plan`
3. `POST /api/travel/recalculate`
4. `GET /api/travel/plans/{plan_id}`
5. `GET /api/data-sources/status`
6. `POST /api/redirect/booking`
7. `GET /api/health`

错误响应语义规则：

| 规则 ID | 规则 |
|---|---|
| ERR-001 | 参数校验失败、业务无可用方案、数据源不可用、LLM 输出非法、重算目标不存在均必须映射到 `ErrorResponse`。 |
| ERR-002 | `request_id` 必须与请求链路一致。 |
| ERR-003 | `retryable` 必须由后端根据错误类型明确给出，不得由前端猜测。 |
| ERR-004 | `details` 可为 null，但字段必须存在，便于前端统一处理。 |

### 11.6 BookingRedirectRequest

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "plan_id",
    "redirect_type"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "plan_id": {
      "type": "string"
    },
    "segment_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "redirect_type": {
      "type": "string",
      "enum": [
        "RAIL_12306",
        "AIRLINE",
        "OTA",
        "MAP_NAVIGATION",
        "RIDE_HAILING"
      ]
    }
  }
}
```

BookingRedirectRequest 语义规则：

| 规则 ID | 规则 |
|---|---|
| BRQ-001 | `redirect_type = MAP_NAVIGATION` 或 `RIDE_HAILING` 时，建议提供 `segment_id`，用于定位具体本地接驳或导航分段。 |
| BRQ-002 | `redirect_type = RAIL_12306`、`AIRLINE` 或 `OTA` 时，若跳转依赖具体主交通分段，应提供 `segment_id`；若为整单聚合跳转，`segment_id` 可为 null。 |
| BRQ-003 | BookingRedirectRequest 只请求生成外部跳转，不得携带第三方账号、密码、支付、自动下单或抢票参数。 |

### 11.7 BookingRedirectResponse

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "redirect",
    "generated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "redirect": {
      "$ref": "#/definitions/BookingRedirect"
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

---

## 12. TravelPlanResponse 与重算 Schema

### 12.1 AsyncJob

```json
{
  "type": "object",
  "required": ["job_id", "job_status", "created_at", "updated_at"],
  "additionalProperties": false,
  "properties": {
    "job_id": { "type": "string" },
    "job_status": { "type": "string", "enum": ["QUEUED", "RUNNING", "WAITING_SOURCE", "PARTIAL_READY", "COMPLETE", "FAILED", "CANCELLED"] },
    "created_at": { "$ref": "#/definitions/TimePoint" },
    "updated_at": { "$ref": "#/definitions/TimePoint" },
    "polling_url": { "type": ["string", "null"] }
  }
}
```

### 12.2 MissingPlanExplanation

```json
{
  "type": "object",
  "required": [
    "plan_type",
    "reason_code",
    "message",
    "source_failure_id"
  ],
  "additionalProperties": false,
  "properties": {
    "plan_type": {
      "type": "string",
      "enum": [
        "DIRECT_RAIL",
        "TRANSFER_RAIL",
        "MULTI_TRANSFER_RAIL",
        "RAIL_TICKET_ENHANCEMENT",
        "DIRECT_FLIGHT",
        "TRANSFER_FLIGHT",
        "MULTI_AIRPORT_FLIGHT",
        "FLIGHT_RAIL_MIXED",
        "GROUND_ONLY",
        "MIXED"
      ]
    },
    "reason_code": {
      "type": "string"
    },
    "message": {
      "type": "string"
    },
    "source_failure_id": {
      "type": [
        "string",
        "null"
      ]
    }
  }
}
```

### 12.3 TravelPlanResponse

`async_job` 必须存在但允许为 `null`。同步 COMPLETE 响应可以返回 `async_job: null`。

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "planning_status",
    "async_job",
    "plans",
    "recommendation_result",
    "source_failures",
    "missing_components",
    "blocked_plan_types",
    "generated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "planning_status": {
      "type": "string",
      "enum": [
        "PENDING",
        "RUNNING",
        "PARTIAL",
        "COMPLETE",
        "FAILED"
      ]
    },
    "async_job": {
      "oneOf": [
        {
          "$ref": "#/definitions/AsyncJob"
        },
        {
          "type": "null"
        }
      ]
    },
    "missing_components": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "RAIL_PRICE",
          "RAIL_AVAILABILITY",
          "RAIL_STOP_SEQUENCE",
          "FLIGHT_PRICE",
          "FLIGHT_STATUS",
          "PREVIOUS_FLIGHT",
          "REALTIME_TRAFFIC",
          "TAXI_ESTIMATE",
          "WEATHER",
          "TRANSFER_MINIMUM_TIME",
          "BOOKING_REDIRECT"
        ]
      }
    },
    "blocked_plan_types": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "DIRECT_RAIL",
          "TRANSFER_RAIL",
          "MULTI_TRANSFER_RAIL",
          "RAIL_TICKET_ENHANCEMENT",
          "DIRECT_FLIGHT",
          "TRANSFER_FLIGHT",
          "MULTI_AIRPORT_FLIGHT",
          "FLIGHT_RAIL_MIXED",
          "GROUND_ONLY",
          "MIXED"
        ]
      }
    },
    "plans": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/TravelPlan"
      }
    },
    "recommendation_result": {
      "oneOf": [
        {
          "$ref": "#/definitions/RecommendationResult"
        },
        {
          "type": "null"
        }
      ]
    },
    "source_failures": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/SourceFailure"
      }
    },
    "missing_plan_explanations": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/MissingPlanExplanation"
      }
    },
    "user_visible_warnings": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "generated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

TravelPlanResponse 状态规则：

1. planning_status = COMPLETE 且存在 eligible plans 时，recommendation_result 必须非 null。
2. planning_status = PENDING/RUNNING 时，recommendation_result 可以为 null。
3. planning_status = FAILED 且无 plans 时，recommendation_result 必须为 null。
4. planning_status = PARTIAL 时，如果已有可推荐方案，可以返回 recommendation_result；否则为 null。
5. plans 允许为空数组，但仅限 PENDING/RUNNING/FAILED 或没有可用方案的 PARTIAL 场景。

### 12.4 SelectedOption

```json
{
  "type": "object",
  "required": ["option_type", "option_id", "option_value", "source_option_version"],
  "additionalProperties": false,
  "properties": {
    "option_type": { "type": "string", "enum": ["SEAT", "CABIN", "TRANSFER_MODE"] },
    "option_id": { "type": "string" },
    "option_value": { "type": "string" },
    "source_option_version": { "type": "string" }
  }
}
```

### 12.5 RecalculateRequest

```json
{
  "type": "object",
  "required": ["schema_version", "request_id", "idempotency_key", "plan_id", "change_type", "target_segment_id", "selected_option", "recalculate_scope"],
  "additionalProperties": false,
  "allOf": [
    {
      "if": {
        "properties": { "change_type": { "const": "SEAT_TYPE" } },
        "required": ["change_type"]
      },
      "then": {
        "properties": {
          "selected_option": {
            "properties": { "option_type": { "const": "SEAT" } },
            "required": ["option_type"]
          }
        }
      }
    },
    {
      "if": {
        "properties": { "change_type": { "const": "CABIN_TYPE" } },
        "required": ["change_type"]
      },
      "then": {
        "properties": {
          "selected_option": {
            "properties": { "option_type": { "const": "CABIN" } },
            "required": ["option_type"]
          }
        }
      }
    },
    {
      "if": {
        "properties": { "change_type": { "const": "LOCAL_TRANSFER_MODE" } },
        "required": ["change_type"]
      },
      "then": {
        "properties": {
          "selected_option": {
            "properties": { "option_type": { "const": "TRANSFER_MODE" } },
            "required": ["option_type"]
          }
        }
      }
    }
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "request_id": { "type": "string" },
    "trace_id": { "type": "string" },
    "correlation_id": { "type": "string" },
    "idempotency_key": { "type": "string" },
    "plan_id": { "type": "string" },
    "change_type": { "type": "string", "enum": ["SEAT_TYPE", "CABIN_TYPE", "LOCAL_TRANSFER_MODE"] },
    "target_segment_id": { "type": "string" },
    "selected_option": { "$ref": "#/definitions/SelectedOption" },
    "recalculate_scope": { "type": "string", "enum": ["PLAN_ONLY", "PLAN_AND_RECOMMENDATION", "FULL_REEVALUATION"] }
  }
}
```

RecalculateRequest 语义规则：

| 规则 ID | 规则 |
|---|---|
| RQ-001 | `change_type = SEAT_TYPE` 时，`selected_option.option_type` 必须为 `SEAT`。 |
| RQ-002 | `change_type = CABIN_TYPE` 时，`selected_option.option_type` 必须为 `CABIN`。 |
| RQ-003 | `change_type = LOCAL_TRANSFER_MODE` 时，`selected_option.option_type` 必须为 `TRANSFER_MODE`。 |
| RQ-004 | `target_segment_id` 必须存在于原始 `TravelPlan.segments[*].segment_id` 中。 |
| RQ-005 | 座席/舱位切换时，`selected_option.option_id` 必须存在于目标 segment 的 `seat_options` 或 `cabin_options` 中。 |
| RQ-006 | 接驳方式切换时，`selected_option.option_value` 必须属于 `LocalTransferSegment.transfer_mode` 枚举。 |

### 12.6 RecalculateChangeSummary

```json
{
  "type": "object",
  "required": ["changed_fields", "cost_delta", "comfort_score_delta", "duration_delta_minutes"],
  "additionalProperties": false,
  "properties": {
    "changed_fields": { "type": "array", "items": { "type": "string" } },
    "cost_delta": { "$ref": "#/definitions/MoneyDelta" },
    "comfort_score_delta": { "type": ["number", "null"] },
    "duration_delta_minutes": { "type": ["integer", "null"] }
  }
}
```

### 12.7 RecalculateResponse

```json
{
  "type": "object",
  "required": [
    "schema_version",
    "request_id",
    "plan",
    "change_summary",
    "updated_at"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.15"
    },
    "request_id": {
      "type": "string"
    },
    "trace_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "correlation_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "idempotency_key": {
      "type": [
        "string",
        "null"
      ]
    },
    "plan": {
      "$ref": "#/definitions/TravelPlan"
    },
    "change_summary": {
      "$ref": "#/definitions/RecalculateChangeSummary"
    },
    "recommendation_result": {
      "oneOf": [
        {
          "$ref": "#/definitions/RecommendationResult"
        },
        {
          "type": "null"
        }
      ]
    },
    "updated_at": {
      "$ref": "#/definitions/TimePoint"
    }
  }
}
```

RecalculateResponse 业务规则：

1. recalculate_scope = PLAN_ONLY 时，recommendation_result 必须为 null 或不返回。
2. recalculate_scope = PLAN_AND_RECOMMENDATION 时，recommendation_result 必须返回非 null。
3. recalculate_scope = FULL_REEVALUATION 时，recommendation_result 必须返回非 null，且 plan 必须重新经过 cost、comfort、risk、data_quality 校验。

---

## 13. 其他核心对象

### 13.1 LLMValidationResult

```json
{
  "type": "object",
  "required": ["status", "schema_valid", "semantic_valid", "repair_attempted", "final_strategy"],
  "additionalProperties": false,
  "properties": {
    "status": { "type": "string", "enum": ["VALID", "SCHEMA_INVALID", "SEMANTIC_INVALID", "REPAIRED_VALID", "FALLBACK_USED"] },
    "schema_valid": { "type": "boolean" },
    "semantic_valid": { "type": "boolean" },
    "invalid_reasons": { "type": "array", "items": { "type": "string" } },
    "repair_attempted": { "type": "boolean" },
    "repair_success": { "type": "boolean" },
    "final_strategy": { "type": "string", "enum": ["USE_ORIGINAL", "USE_REPAIRED", "DETERMINISTIC_FALLBACK"] },
    "llm_call_id": { "type": ["string", "null"] },
    "prompt_version": { "type": ["string", "null"] },
    "model_name": { "type": ["string", "null"] }
  }
}
```

### 13.2 RecommendationSlot

三类推荐卡片的统一结构。V1.15 起，推荐结果不再只依赖自然语言或 Semantic Validator 约束 `status` 与 `plan_id` 的关系，基础条件可直接由 JSON Schema 校验。

```json
{
  "type": "object",
  "required": ["recommendation_type", "status", "plan_id", "reason"],
  "additionalProperties": false,
  "allOf": [
    {
      "if": {
        "properties": { "status": { "const": "AVAILABLE" } },
        "required": ["status"]
      },
      "then": {
        "properties": {
          "plan_id": { "type": "string", "minLength": 1 }
        }
      }
    },
    {
      "if": {
        "properties": { "status": { "enum": ["NOT_AVAILABLE", "BLOCKED"] } },
        "required": ["status"]
      },
      "then": {
        "properties": {
          "plan_id": { "type": "null" },
          "reason": { "type": "string", "minLength": 1 }
        }
      }
    },
    {
      "if": {
        "properties": { "status": { "const": "BLOCKED" } },
        "required": ["status"]
      },
      "then": {
        "properties": {
          "block_reason_code": { "type": "string", "minLength": 1 }
        },
        "required": ["block_reason_code"]
      }
    }
  ],
  "properties": {
    "recommendation_type": { "type": "string", "enum": ["CHEAPEST", "MOST_COMFORTABLE", "BALANCED"] },
    "status": { "type": "string", "enum": ["AVAILABLE", "NOT_AVAILABLE", "BLOCKED"] },
    "plan_id": { "type": ["string", "null"] },
    "reason": { "type": "string", "minLength": 1 },
    "risk_summary": { "type": ["string", "null"] },
    "block_reason_code": { "type": ["string", "null"] },
    "confidence_level": { "type": ["string", "null"], "enum": ["HIGH", "MEDIUM", "LOW", null] },
    "source": { "type": ["string", "null"], "enum": ["LLM", "DETERMINISTIC_FALLBACK", "RULE_BASED", null] }
  }
}
```

### 13.3 RecommendationResult

```json
{
  "type": "object",
  "required": ["schema_version", "recommendation_id", "recommendation_source", "recommendations", "llm_validation_result"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "string", "const": "1.15" },
    "recommendation_id": { "type": "string" },
    "recommendation_source": { "type": "string", "enum": ["LLM", "DETERMINISTIC_FALLBACK", "RULE_BASED"] },
    "recommendations": { "type": "array", "minItems": 3, "maxItems": 3, "items": { "$ref": "#/definitions/RecommendationSlot" } },
    "llm_validation_result": { "$ref": "#/definitions/LLMValidationResult" }
  }
}
```

### 13.4 BookingRedirect

BookingRedirect 只表达外部跳转，不表达自动登录、自动下单、自动支付、自动抢票或保存第三方账号密码。交易边界必须固定为 `REDIRECT_ONLY`。

```json
{
  "type": "object",
  "required": ["redirect_id", "redirect_type", "display_name", "url_available", "generated_at", "expires_at", "transaction_boundary", "data_source"],
  "additionalProperties": false,
  "allOf": [
    {
      "if": {
        "properties": { "url_available": { "const": true } },
        "required": ["url_available"]
      },
      "then": {
        "anyOf": [
          { "properties": { "url": { "type": "string", "minLength": 1 } }, "required": ["url"] },
          { "properties": { "deep_link": { "type": "string", "minLength": 1 } }, "required": ["deep_link"] }
        ]
      }
    },
    {
      "if": {
        "properties": { "url_available": { "const": false } },
        "required": ["url_available"]
      },
      "then": {
        "properties": {
          "fallback_instruction": { "type": "string", "minLength": 1 }
        },
        "required": ["fallback_instruction"]
      }
    }
  ],
  "properties": {
    "redirect_id": { "type": "string" },
    "redirect_type": { "type": "string", "enum": ["RAIL_12306", "AIRLINE", "OTA", "MAP_NAVIGATION", "RIDE_HAILING"] },
    "display_name": { "type": "string" },
    "url": { "type": ["string", "null"] },
    "url_available": { "type": "boolean" },
    "deep_link": { "type": ["string", "null"] },
    "fallback_instruction": { "type": ["string", "null"] },
    "generated_at": { "$ref": "#/definitions/TimePoint" },
    "expires_at": { "oneOf": [{ "$ref": "#/definitions/TimePoint" }, { "type": "null" }] },
    "transaction_boundary": { "type": "string", "const": "REDIRECT_ONLY" },
    "data_source": { "$ref": "#/definitions/DataSourceMetadata" }
  }
}
```

跳转语义规则：

| 规则 ID | 规则 |
|---|---|
| BR-001 | `url_available = true` 时，`url` 或 `deep_link` 至少一个必须非空。 |
| BR-002 | `url_available = false` 时，`fallback_instruction` 必须非空。 |
| BR-003 | 所有购票、地图、打车能力均只能跳转，不得自动登录、自动下单、自动支付、自动抢票。 |
| BR-004 | `transaction_boundary` 必须恒等于 `REDIRECT_ONLY`。 |
| BR-005 | 第三方跳转链接必须带 `generated_at`；可过期链接必须提供 `expires_at`。 |

---
## 14. V1.14 修复落实表

| Review 问题 | 风险影响 | V1.14 处理结果 |
|---|---|---|
| `ErrorResponse` 的规则要求 `retryable` 必须由后端给出、`details` 字段必须存在且可为 null，但 V1.13 Schema 中二者没有纳入 `required`，且 `details` 只允许 object。 | 前端错误处理、接口测试和 Codex 实现可能出现错误路径字段缺失；`details: null` 的合法错误响应会被 Schema 拒绝。 | 已将 `retryable` 与 `details` 加入 `ErrorResponse.required`，并将 `details` 改为 `oneOf: object/null`。 |
| 机器可读 Schema 交付物说明仍写作 “V1.12 冻结后建议同步维护”。 | 当前冻结版本、文件路径和 CI 交付基线存在歧义，容易让后端/前端类型生成引用旧版本。 | 已改为 “V1.14 冻结后建议同步维护”，并将主文档路径更新为 `/docs/schema/AI_Travel_Planner_Data_Schema_V1.15.md`。 |
| `RecommendationSlot` 说明仍写 “V1.12 后”。 | 虽不影响机器校验，但会造成冻结版本语义混乱。 | 已改为 “V1.14 起”。 |
| `BookingRedirectRequest` 只有结构定义，缺少请求侧语义规则。 | 接驳导航、打车、购票跳转可能不知道是否必须绑定 `segment_id`，也缺少对“不得携带交易参数”的请求侧约束。 | 新增 BRQ-001 至 BRQ-003，明确地图/打车建议绑定 segment，购票类可整单或分段跳转，且请求不得携带账号、支付、下单或抢票参数。 |
| `schema_version.const` 仍为 1.13。 | V1.14 文件与运行时校验版本不一致。 | 已统一更新为 `1.14`。 |

---

## 15. V1.15 冻结判断

V1.15 是基于 V1.14 的冻结前收口一致性修复版本，不新增新的业务范围，主要修复链路追踪、数据源 fallback 审计字段和冻结条件表述。若 PRD 或系统架构不继续新增业务范围，且下列冻结前验证项通过，本版本可作为开发冻结版本。

冻结前必须验证：

1. 所有 Markdown 中的 JSON 片段可被抽取为合法 JSON Schema。
2. 所有当前版本 `schema_version.const` 必须为 `1.15`。
3. 推荐结果三卡位规则必须覆盖 REC-001 至 REC-012 单元测试，并额外覆盖 `RecommendationSlot` 条件校验和 `reason` 非空校验。
4. RecalculateRequest 必须覆盖 RQ-001 至 RQ-006 单元测试。
5. Segment 选中项一致性必须覆盖 SEG-001 至 SEG-006 单元测试。
6. SourceFailure 必须覆盖 SF-001 至 SF-004 单元测试，尤其是 fallback 成功、fallback 失败、BLOCK_PLAN 三类路径。
7. TravelPlanResponse 必须在 COMPLETE、PARTIAL、RUNNING、FAILED 四类状态下均有示例响应。
8. RecalculateResponse 必须对三种 recalculate_scope 均有示例响应。
9. ErrorResponse 必须被所有 API 4xx / 5xx 错误路径复用，且 `retryable`、`details` 字段必须存在。
10. BookingRedirect 必须覆盖 BR-001 至 BR-005、API-006 单元测试；BookingRedirectRequest 必须覆盖 BRQ-001 至 BRQ-003。
11. SourceFailure 日志字段与监控字段必须统一使用 `failure_class` 与 `message`，并能通过 `request_id`、`trace_id`、`correlation_id` 串联 API 响应。
12. `/api/health` 的 HealthResponse 必须覆盖 `schema_version` 校验。
13. `/api/data-sources/status` 必须使用 `DataSourceRuntimeStatus`，不得直接返回 DataSourceConfig。
14. `DataSourceMetadata` 在候选站点、候选机场、主交通分段、本地接驳分段、座席/舱位选项、费用明细、方案汇总中的审计字段必须可稳定输出。
15. `/schemas/*.schema.json` 必须从本文档同步导出，并在 CI 中完成 JSON Schema 语法校验、示例数据校验和关键业务语义用例校验。

开发冻结建议：

1. 后续不得在 V1.x 中删除字段、删除 enum 或改变 required 语义。
2. 如需新增支付、下单、账号登录、抢票等交易能力，必须进入 V2.0 架构与 Schema 评审。
3. 如需改变推荐卡片数量或推荐类型，也必须进入 V2.0。
4. V1.15 冻结后，PRD、系统架构、Prompt 文档只能引用本 Schema，不得重复定义接口字段。
5. 后续评审应优先使用自动化检查清单，而不是继续让 LLM 逐版“肉眼找茬”；只有新增业务范围或自动化校验失败时才进入下一版。
