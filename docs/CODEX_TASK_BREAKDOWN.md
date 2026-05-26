# AI 出行规划应用 Codex 开发任务拆解 V1

版本：V1  
日期：2026-05-26

对齐文档：

- PRD：AI Travel Planner PRD V2.1
- 系统架构设计：AI Travel Planner System Architecture V1.1
- 核心数据结构与 JSON Schema：AI_Travel_Planner_Data_Schema_V1.15
- 数据源准入规范：AI_Travel_Planner_Data_Source_Governance_V1.1
- LLM Prompt 设计：AI_Travel_Planner_LLM_Prompt_Design_V1

---

## Changelog

| 日期 | 版本 | 更改点 |
|---|---|---|
| 2026-05-26 | V1 | 创建 Codex 开发任务拆解初版，定义项目技术栈、目录结构、阶段任务、模块输入输出、验收标准、mock 数据闭环、禁止事项和开发顺序。 |

---

## 1. 文档目标

本文档用于把已经完成的产品设计、系统架构、Schema、数据源准入规范和 LLM Prompt 设计，转换为 Codex 可执行的开发任务。

本文档不是产品需求说明，也不是系统设计说明，而是开发实施任务书。

Codex 必须基于本文档逐项实现，不得自行改变核心架构、Schema、数据源边界和 LLM 边界。

---

## 2. 开发总原则

### 2.1 Web App first, App later

第一阶段实现 Web App。

后续 App 复用：

1. 后端 API。
2. Pydantic models。
3. Schema。
4. Travel Planning Orchestrator。
5. Data Source Adapters。
6. LLM wrapper。
7. Deterministic fallback。
8. Scoring / Risk / Cost engines。

### 2.2 Mock first, real source later

第一阶段必须用 mock 数据跑通完整产品闭环。

不得为了“效果”直接接入未知数据源、逆向接口或无授权接口。

真实数据源接入必须等待：

1. 数据源准入规范通过。
2. DataSourceConfig 注册。
3. 商务 Review 完成。
4. PROD 许可确认。

### 2.3 Schema first

所有接口、模型、前端类型必须对齐：

```text
AI_Travel_Planner_Data_Schema_V1.15
```

不得私自新增核心字段。

如确需扩展，必须：

1. 先更新 Schema。
2. 再更新本文档。
3. 再实现代码。

### 2.4 LLM constrained by deterministic candidate pool

LLM 不得生成事实数据。

LLM 只能：

1. 解析自然语言为 TravelRequest。
2. 从 candidate_plan_ids 里选择推荐。
3. 生成推荐解释。
4. 修复非法 JSON 输出。

LLM 不得：

1. 生成车次。
2. 生成航班。
3. 生成价格。
4. 生成余票。
5. 生成地图路线。
6. 生成跳转链接。
7. 修改候选方案事实字段。

---

## 3. 推荐技术栈

### 3.1 Monorepo

建议项目结构：

```text
ai-travel-planner/
  backend/
  frontend/
  docs/
  schemas/
  mock_data/
  scripts/
  tests/
```

### 3.2 Backend

推荐：

```text
Python 3.11+
FastAPI
Pydantic v2
Uvicorn
pytest
httpx
python-dotenv
```

后续可选：

```text
PostgreSQL
Redis
Celery / RQ
SQLAlchemy
```

第一阶段暂不强制引入数据库。可以先使用内存存储 + mock 文件。

### 3.3 Frontend

推荐：

```text
React
TypeScript
Vite 或 Next.js
Tailwind CSS
shadcn/ui 可选
Zustand 可选
```

第一阶段目标是可运行 Web App，不追求复杂 UI 动效。

### 3.4 Schema / Type 生成

建议：

1. 后端手写 Pydantic models，对齐 Schema。
2. 前端手写 TypeScript types，初期不强依赖自动生成。
3. 后续引入 JSON Schema to TypeScript / Pydantic generation。

---

## 4. 顶层目录结构

Codex 应创建以下结构：

```text
ai-travel-planner/
  README.md
  docs/
    PRD.md
    SYSTEM_ARCHITECTURE.md
    DATA_SCHEMA.md
    DATA_SOURCE_GOVERNANCE.md
    LLM_PROMPT_DESIGN.md
    CODEX_TASK_BREAKDOWN.md

  schemas/
    common.definitions.schema.json
    travel-request.schema.json
    parse-travel-request-response.schema.json
    travel-plan-response.schema.json
    get-travel-plan-response.schema.json
    llm-recommendation-input.schema.json
    llm-recommendation-output.schema.json
    recalculate-request.schema.json
    recalculate-response.schema.json
    booking-redirect-request.schema.json
    booking-redirect-response.schema.json
    error-response.schema.json
    data-source-status.schema.json
    health-response.schema.json

  backend/
    app/
      main.py
      api/
      core/
      schemas/
      models/
      services/
      engines/
      adapters/
      llm/
      data_sources/
      mock/
      utils/
      tests/

  frontend/
    src/
      api/
      components/
      pages/
      types/
      stores/
      utils/
      mock/

  mock_data/
    shanghai_qingdao/
      travel_request.json
      station_candidates.json
      airport_candidates.json
      local_transfer_segments.json
      rail_candidates.json
      flight_candidates.json
      travel_plans.json
      llm_recommendation_input.json
      llm_recommendation_output.json
```

---

## 5. Phase 0：项目骨架

### Task 0.1 创建 monorepo

目标：

创建基础仓库结构。

产出：

1. 顶层目录。
2. README。
3. backend 目录。
4. frontend 目录。
5. docs 目录。
6. schemas 目录。
7. mock_data 目录。

验收：

1. 目录结构完整。
2. README 中说明启动方式。
3. docs 中放置当前设计文档引用。
4. 不包含真实 API key。

---

### Task 0.2 创建 backend FastAPI 项目

目标：

创建后端基础服务。

接口：

1. `GET /api/health`
2. `GET /api/data-sources/status`

验收：

1. `uvicorn app.main:app --reload` 可启动。
2. `/api/health` 返回 HealthResponse。
3. `/api/data-sources/status` 返回 DataSourceStatusResponse。
4. 所有错误响应复用 ErrorResponse。
5. 响应包含 schema_version = 1.15。

---

### Task 0.3 创建 frontend Web App

目标：

创建前端基础应用。

页面：

1. 首页。
2. 结果页占位。
3. 数据源状态页占位。

验收：

1. 前端可启动。
2. 能调用 `/api/health`。
3. 能显示服务状态。
4. TypeScript 无错误。

---

### Task 0.4 配置基础开发脚本

建议命令：

```text
make backend-dev
make frontend-dev
make test
make lint
```

验收：

1. 一条命令可启动后端。
2. 一条命令可启动前端。
3. 一条命令可运行测试。

---

## 6. Phase 1：Schema 与数据模型

### Task 1.1 创建 Pydantic common models

目标：

实现公共模型：

1. Money
2. MoneyDelta
3. TimePoint
4. GeoPoint
5. NormalizedScores
6. CacheMetadata
7. DataSourceMetadata
8. DataSourceConfig
9. SourceFailure
10. ErrorResponse

验收：

1. 所有模型字段与 Schema V1.15 对齐。
2. Money 使用 amount_minor / currency / scale。
3. additionalProperties 对应 Pydantic extra = "forbid"。
4. pytest 覆盖合法和非法样例。

---

### Task 1.2 创建 TravelRequest models

目标：

实现：

1. TravelHardConstraints
2. TravelSoftPreferences
3. TravelRequest
4. ParseTravelRequestResponse

验收：

1. TravelRequest required 字段对齐 V1.15。
2. 时间字段使用 TimePoint。
3. hard_constraints / soft_preferences required。
4. allowed / excluded transport modes 使用统一 enum。
5. schema_version 固定为 1.15。

---

### Task 1.3 创建候选对象 models

目标：

实现：

1. StationCandidate
2. AirportCandidate
3. GeoPoint

验收：

1. estimated_transfer_cost 使用 Money | None。
2. data_source required。
3. ranking_reasons 支持 array。
4. 不允许 unknown field。

---

### Task 1.4 创建 Segment models

目标：

实现：

1. SeatOption
2. CabinOption
3. RailSegment
4. FlightSegment
5. LocalTransferSegment
6. TicketEnhancement

验收：

1. seat_options / cabin_options minItems = 1。
2. selected_seat_option_id / selected_cabin_option_id 存在。
3. LocalTransferSegment 使用 origin / destination / estimated_cost / traffic_risk / redirect_info。
4. normalized_scores 有定义。
5. 所有 segment 带 data_source。

---

### Task 1.5 创建 TravelPlan models

目标：

实现：

1. CostBreakdown
2. ComfortScore
3. RiskItem
4. RiskAssessment
5. DataQuality
6. BookingRedirect
7. TravelPlan
8. TravelPlanResponse
9. GetTravelPlanResponse

验收：

1. total_cost 使用 Money。
2. CostBreakdown.items.amount 使用 Money。
3. TravelPlan 包含 recommendation_eligibility / can_be_selected_by_llm。
4. TravelPlanResponse 包含 source_failures / missing_components / blocked_plan_types。
5. async_job 允许 null。

---

### Task 1.6 创建 LLM models

目标：

实现：

1. LLMRecommendationInput
2. LLMRecommendationOutput
3. RecommendationSlot
4. RecommendationResult
5. LLMValidationResult

验收：

1. LLMRecommendationInput 包含 candidate_plan_ids。
2. LLMRecommendationOutput 不包含 candidate_plan_ids。
3. selected_recommendations minItems = 3 / maxItems = 3。
4. 三卡位可表达 AVAILABLE / NOT_AVAILABLE / BLOCKED。
5. 不允许 unknown fields。

---

### Task 1.7 创建 Recalculate models

目标：

实现：

1. RecalculateRequest
2. SelectedOption
3. RecalculateResponse
4. RecalculateChangeSummary
5. MoneyDelta

验收：

1. selected_option 包含 option_type / option_id / option_value / source_option_version。
2. recalculate_scope 可表达局部重算。
3. cost_delta 使用 MoneyDelta，允许负数。
4. RecalculateResponse 透传 trace_id / correlation_id / idempotency_key。

---

## 7. Phase 2：Mock 数据与 Adapter

### Task 2.1 DataSourceConfig loader

目标：

实现数据源白名单配置读取。

产出：

```text
backend/app/data_sources/config_loader.py
backend/app/data_sources/data_sources.dev.json
backend/app/data_sources/data_sources.test.json
backend/app/data_sources/data_sources.prod.json
```

验收：

1. DEV 可加载 mock 数据源。
2. PROD 禁止加载 PENDING_REVIEW。
3. PROD 禁止加载 C 级数据源。
4. DataSourceConfig 校验失败时返回 ErrorResponse。
5. `/api/data-sources/status` 不返回 DataSourceConfig，只返回 DataSourceRuntimeStatus。

---

### Task 2.2 Mock MapDataProvider

目标：

实现地址解析和本地接驳 mock。

输入：

1. origin_text
2. destination_text
3. station / airport location

输出：

1. LocationCandidate
2. LocalTransferSegment

验收：

1. 上海嘉定南翔格林公馆可解析。
2. 青岛金水假日酒店可解析。
3. 到上海虹桥站 / 虹桥机场可生成接驳。
4. 到青岛北 / 青岛胶东机场可生成接驳。
5. 所有输出带 DataSourceMetadata。

---

### Task 2.3 Mock RailDataProvider

目标：

实现高铁 mock 数据。

场景：

1. 上海虹桥 → 青岛北直达。
2. 上海虹桥 → 南京南 → 青岛北中转。
3. 票源增强 S 档。
4. 票源增强 A 档。
5. BLOCKED / 不可选方案。

验收：

1. 可返回 RailSegment。
2. 可返回 SeatOption。
3. 可返回 stop_sequence。
4. 可支持 TicketEnhancement。
5. 不合法票源增强可标记 BLOCKED。

---

### Task 2.4 Mock FlightDataProvider

目标：

实现航班 mock 数据。

场景：

1. 上海虹桥 → 青岛胶东直飞。
2. 上海浦东 → 青岛胶东直飞。
3. 上海 → 南京/济南 → 青岛中转示例。
4. 航班延误风险缺失场景。
5. 前序航班数据缺失场景。

验收：

1. 可返回 FlightSegment。
2. 可返回 CabinOption。
3. 可表达 previous_flight_risk_available。
4. 可触发 SourceFailure。
5. 可影响 DataQuality。

---

### Task 2.5 Mock BookingRedirectProvider

目标：

实现跳转 mock。

类型：

1. RAIL_12306
2. AIRLINE
3. OTA
4. MAP_NAVIGATION
5. RIDE_HAILING

验收：

1. 能生成 BookingRedirectResponse。
2. 无 URL 时返回 fallback_instruction。
3. 不包含自动登录 / 自动下单 / 自动支付字段。
4. 失败时返回 ErrorResponse。

---

## 8. Phase 3：后端 API

### Task 3.1 GET /api/health

输出：

HealthResponse。

验收：

1. schema_version = 1.15。
2. status = OK / DEGRADED / DOWN。
3. checked_at 使用 TimePoint。
4. 错误返回 ErrorResponse。

---

### Task 3.2 GET /api/data-sources/status

输出：

DataSourceStatusResponse。

验收：

1. sources 使用 DataSourceRuntimeStatus。
2. 不返回 DataSourceConfig。
3. 不暴露 token / key / stack trace。
4. 包含 request_id。
5. 支持 DEGRADED / DOWN 状态。

---

### Task 3.3 POST /api/travel/parse

输入：

用户自然语言。

处理：

1. 调用 Intent Parser。
2. Schema validation。
3. Semantic validation。
4. repair once。
5. still invalid -> ErrorResponse。

输出：

ParseTravelRequestResponse。

验收：

1. 能解析上海 → 青岛示例。
2. 用户未指定偏好时输出三类偏好。
3. 用户只要最便宜时只输出 CHEAPEST。
4. 不坐飞机能进入 excluded_transport_modes。
5. 不生成车次 / 航班 / 价格。

---

### Task 3.4 POST /api/travel/plan

输入：

TravelRequest 或 raw_user_input。

处理链路：

1. 如果是 raw_user_input，先 parse。
2. 解析地点。
3. 生成候选车站 / 机场。
4. 生成接驳。
5. 生成 rail candidates。
6. 生成 flight candidates。
7. 生成 ticket enhancement candidates。
8. 组合 TravelPlan。
9. 计算费用。
10. 计算舒适度。
11. 计算风险。
12. 过滤 BLOCKED。
13. 构造 LLMRecommendationInput。
14. 调 LLM Recommendation。
15. 校验。
16. repair or deterministic fallback。
17. 返回 TravelPlanResponse。

验收：

1. 返回 planning_status。
2. 返回 async_job 可为 null。
3. 返回 source_failures[]。
4. 返回 missing_components[]。
5. 返回 blocked_plan_types[]。
6. 返回三张推荐卡或明确 NOT_AVAILABLE。
7. 所有事实字段有 DataSourceMetadata。

---

### Task 3.5 GET /api/travel/plans/{plan_id}

输出：

GetTravelPlanResponse。

验收：

1. plan_id 存在时返回 TravelPlan。
2. plan_id 不存在时返回 ErrorResponse。
3. plan 过期时 plan_lifecycle_status = EXPIRED 或返回明确错误。
4. 透传 trace_id / correlation_id。

---

### Task 3.6 POST /api/travel/recalculate

输入：

RecalculateRequest。

处理：

1. 校验 plan_id。
2. 校验 target_segment_id。
3. 校验 selected_option 是否来自原方案合法 option。
4. 按 recalculate_scope 重算。
5. 返回 RecalculateResponse。

验收：

1. 切换二等座 → 一等座，费用变化。
2. 切换经济舱 → 商务舱，费用变化。
3. 切换接驳方式，费用和舒适度变化。
4. 返回 RecalculateChangeSummary。
5. cost_delta 支持正负。
6. 不合法 option_id 返回 ErrorResponse。

---

### Task 3.7 POST /api/redirect/booking

输入：

BookingRedirectRequest。

输出：

BookingRedirectResponse。

验收：

1. 可生成 12306 mock 跳转。
2. 可生成航司 mock 跳转。
3. 可生成地图 mock 跳转。
4. 不包含自动登录 / 自动下单 / 自动支付。
5. generated_at 存在。
6. 错误返回 ErrorResponse。

---

## 9. Phase 4：核心引擎

### Task 4.1 Travel Planning Orchestrator

目标：

实现端到端编排。

验收：

1. 一次请求能生成 TravelPlanResponse。
2. 各模块失败能降级。
3. 数据源失败能生成 SourceFailure。
4. 安全关键失败能阻断推荐。
5. trace_id / correlation_id 全链路传递。

---

### Task 4.2 Candidate Generator

目标：

组合候选方案。

输入：

1. stations
2. airports
3. rail segments
4. flight segments
5. local transfer segments

输出：

TravelPlan[]

验收：

1. 生成 DIRECT_RAIL。
2. 生成 TRANSFER_RAIL。
3. 生成 DIRECT_FLIGHT。
4. 生成 TRANSFER_FLIGHT。
5. 生成 FLIGHT_RAIL_MIXED。
6. 生成 RAIL_TICKET_ENHANCEMENT。
7. 过滤无法满足 hard_constraints 的方案。

---

### Task 4.3 Ticket Enhancement Engine

目标：

实现票源增强 S/A 规则。

验收：

1. ticket_covers_actual_route = true 才可候选。
2. requires_onboard_supplement = true 不进入主推荐。
3. S 档规则生效。
4. A 档规则生效。
5. 超过 A 档 NOT_RECOMMENDED。
6. 票面起点晚于实际上车站 BLOCKED。
7. coverage_validation 有 validation_source / validation_rule_version。

---

### Task 4.4 Cost Calculator

目标：

计算费用。

验收：

1. 所有金额使用 Money。
2. 差价使用 MoneyDelta。
3. total_cost = items 汇总。
4. 座席/舱位切换后重算。
5. 接驳方式切换后重算。
6. 不使用 float 做金额累加。

---

### Task 4.5 Comfort Scoring Engine

目标：

计算舒适度。

验收：

1. total_score 0–10。
2. breakdown 0–10。
3. score_vector 使用 NormalizedScores。
4. 数据缺失时 confidence 降低。
5. 座席/舱位变化影响 comfort。

---

### Task 4.6 Risk Assessment Engine

目标：

生成风险。

验收：

1. 生成 RiskItem。
2. 高铁中转过短产生风险。
3. 航班中转过短产生风险。
4. 买短补长高风险。
5. 安全关键数据缺失 BLOCKED。
6. risk_assessment.recommendation_allowed 正确。

---

### Task 4.7 Deterministic Rule Engine

目标：

强制执行不可交给 LLM 的规则。

规则：

1. hard_constraints。
2. BLOCKED。
3. EXPIRED。
4. INVALIDATED。
5. can_be_selected_by_llm = false。
6. recommendation_eligibility = BLOCKED。
7. 票源增强安全规则。
8. 航班最小中转时间。
9. 数据源安全关键缺失。

验收：

1. 被阻断方案不进入 LLM 输入候选池。
2. 被阻断方案出现在 blocked_plan_types 或 rejected reasons。
3. 所有阻断有 block_reason_code / message。

---

### Task 4.8 LLM Wrapper + Validators

目标：

实现 LLM 调用与校验。

验收：

1. 调用 Intent Parser。
2. 调用 Recommendation Prompt。
3. Schema validation。
4. Semantic validation。
5. Repair once。
6. fallback。
7. 记录 LLMValidationResult。
8. 记录 prompt_version / model_name / latency。

---

## 10. Phase 5：前端 Web App

### Task 5.1 首页输入页

功能：

1. 自然语言输入。
2. 示例 prompt。
3. 提交按钮。
4. loading 状态。

验收：

1. 可提交上海 → 青岛示例。
2. 错误时展示 ErrorResponse.user_visible_message。
3. 不展示技术堆栈错误。

---

### Task 5.2 规划中 / partial 状态

功能：

1. 展示 planning_status。
2. 展示 progress。
3. 展示 missing_components。
4. 展示 user_visible_warnings。

验收：

1. PARTIAL 可展示。
2. FAILED 可展示。
3. COMPLETE 自动进入结果页。

---

### Task 5.3 结果页三卡

功能：

1. 最便宜。
2. 最舒适。
3. 综合推荐。

验收：

1. 三个 slot 固定展示。
2. NOT_AVAILABLE 也展示原因。
3. BLOCKED 展示原因。
4. AVAILABLE 可进入详情。
5. reason 非空。

---

### Task 5.4 方案详情时间线

功能：

1. 展示 segments。
2. 展示 RailSegment。
3. 展示 FlightSegment。
4. 展示 LocalTransferSegment。
5. 展示中转 / 等待信息。

验收：

1. 门到门完整展示。
2. 接驳费用展示 estimated。
3. 高铁 / 航班信息只展示数据源返回字段。
4. 不展示 LLM 编造字段。

---

### Task 5.5 费用与舒适度

功能：

1. CostBreakdown。
2. ComfortScore。
3. RiskAssessment。
4. DataQuality。

验收：

1. Money 正确格式化。
2. 不直接显示 amount_minor。
3. 舒适度拆解可展开。
4. 风险项结构化展示。
5. 数据缺失提示可见。

---

### Task 5.6 座席/舱位/接驳方式切换

功能：

1. 切换高铁座席。
2. 切换飞机舱位。
3. 切换接驳方式。
4. 调用 recalculate。

验收：

1. 只能选择后端返回的 option_id。
2. 调用 RecalculateRequest。
3. 使用 change_summary 更新 UI。
4. 费用和舒适度变化明确。
5. 不合法选择有错误提示。

---

### Task 5.7 跳转按钮

功能：

1. 12306。
2. 航司。
3. OTA。
4. 地图。
5. 打车。

验收：

1. 点击前调用 /api/redirect/booking。
2. url_available = true 时跳转。
3. url_available = false 时展示 fallback_instruction。
4. 不展示自动下单/支付文案。

---

### Task 5.8 数据源展示

功能：

1. 展示数据来源。
2. 展示更新时间。
3. 展示价格和余票以最终平台为准。
4. 展示数据缺失原因。

验收：

1. 可查看 DataSourceMetadata。
2. PARTIAL 时解释缺失数据。
3. SourceFailure 有用户可见提示。

---

## 11. Phase 6：Mock 上海 → 青岛端到端

### Task 6.1 Mock 用例准备

必须准备以下 mock：

1. 上海嘉定南翔格林公馆。
2. 上海虹桥站。
3. 上海虹桥机场。
4. 上海浦东机场。
5. 青岛北站。
6. 青岛胶东机场。
7. 青岛金水假日酒店。

### Task 6.2 最便宜方案

期望：

1. 打车到上海虹桥站。
2. 高铁到青岛北。
3. 打车到酒店。
4. 总价最低。
5. 推荐类型 CHEAPEST。

### Task 6.3 最舒适方案

期望：

1. 打车到机场。
2. 航班到青岛。
3. 打车到酒店。
4. 舒适度最高或解释为什么不是最高。
5. 推荐类型 MOST_COMFORTABLE。

### Task 6.4 综合推荐

期望：

1. 在价格、耗时、风险、舒适度之间平衡。
2. 不一定等于最便宜。
3. 不一定等于最舒适。
4. 解释 tradeoff。

### Task 6.5 票源增强 S/A

期望：

1. S 档可进入候选。
2. A 档谨慎推荐。
3. 超过 A 档不进主推荐。
4. 买短补长不进主推荐。
5. BLOCKED 不进 LLM。

### Task 6.6 数据源失败

模拟：

1. 前序航班缺失。
2. 高铁余票失败。
3. 地图 fallback。
4. 安全关键站序失败。

验收：

1. SourceFailure 生成。
2. MissingPlanExplanation 生成。
3. blocked_plan_types 正确。
4. 前端解释清楚。

---

## 12. Phase 7：测试体系

### Task 7.1 Backend unit tests

覆盖：

1. Pydantic validation。
2. Money 精度。
3. TimePoint。
4. DataSourceConfig 校验。
5. SourceFailure。
6. TicketEnhancement。
7. RiskAssessment。
8. Deterministic fallback。

### Task 7.2 API tests

覆盖：

1. /api/health。
2. /api/data-sources/status。
3. /api/travel/parse。
4. /api/travel/plan。
5. /api/travel/recalculate。
6. /api/travel/plans/{plan_id}。
7. /api/redirect/booking。

### Task 7.3 LLM tests

覆盖：

1. Intent Parser 正常。
2. Intent Parser 非法输出 repair。
3. Recommendation 正常三卡。
4. LLM 输出不存在 plan_id。
5. LLM 选择 BLOCKED。
6. LLM 少一个 slot。
7. Repair 失败 fallback。

### Task 7.4 Frontend tests

覆盖：

1. 首页输入。
2. loading。
3. partial。
4. 三卡展示。
5. 详情页。
6. re-calculate。
7. ErrorResponse。
8. data source display。

---

## 13. 禁止事项

Codex 禁止：

1. 调用未知真实接口。
2. 调用逆向 12306。
3. 抓取第三方网页。
4. 绕过验证码。
5. 绕过登录态。
6. 自动下单。
7. 自动支付。
8. 把 LLM 当事实源。
9. 让 LLM 生成 TravelPlan。
10. 让 LLM 修改候选方案。
11. 使用 float 计算金额。
12. 直接返回临时错误结构。
13. 暴露 DataSourceConfig 给前端状态接口。
14. 跳过 Semantic Validator。
15. 跳过 DataSourceConfig 校验。

---

## 14. 开发顺序建议

建议执行顺序：

```text
Phase 0：项目骨架
Phase 1：Schema / Models
Phase 2：Mock DataSource Adapters
Phase 3：Backend APIs
Phase 4：Core Engines
Phase 5：Frontend Web App
Phase 6：Mock 上海 → 青岛端到端
Phase 7：Testing
```

不要先做漂亮 UI。

不要先接真实数据源。

不要先做 App。

先跑通最终产品闭环。

---

## 15. 第一阶段完成定义

第一阶段完成必须满足：

1. Web App 可输入自然语言。
2. 后端可解析 TravelRequest。
3. 可用 mock 数据生成门到门 TravelPlan。
4. 可生成高铁方案。
5. 可生成航班方案。
6. 可生成接驳方案。
7. 可生成票源增强方案。
8. 可计算费用。
9. 可计算舒适度。
10. 可计算风险。
11. 可输出三张推荐卡。
12. LLM 输出非法可 repair / fallback。
13. 前端可展示三卡和详情。
14. 可切换座席 / 舱位 / 接驳方式并重算。
15. 可展示数据源。
16. 可展示失败原因。
17. 可触发跳转 mock。
18. 所有金额使用 Money。
19. 所有错误使用 ErrorResponse。
20. 所有事实字段携带 DataSourceMetadata。

---

## 16. 后续真实数据源接入顺序

在 mock 闭环完成后，再按以下顺序接真实数据源：

1. 地图数据源。
2. 地址解析。
3. 本地接驳路线。
4. 高铁静态站点 / 时刻。
5. 高铁票价 / 余票。
6. 航班计划。
7. 航班动态。
8. 航班价格。
9. OTA / 跳转。
10. 打车平台跳转。

每接一个真实数据源，都必须：

1. 更新 DataSourceConfig。
2. 完成商务 Review。
3. 增加 fallback。
4. 增加 SourceFailure 测试。
5. 增加 DataSourceRuntimeStatus。
6. 增加前端数据来源展示。

---

## 17. 交付物清单

Codex 第一阶段应交付：

```text
backend FastAPI service
frontend Web App
Pydantic models
TypeScript types
Mock adapters
Travel planning orchestrator
Cost calculator
Comfort scoring engine
Risk assessment engine
Ticket enhancement engine
LLM wrapper
Semantic validator
Deterministic fallback
Recalculate API
Booking redirect API
Data source status API
Health API
Mock Shanghai → Qingdao E2E dataset
Backend tests
Frontend tests
README
```

---

## 18. 验收 Checklist

| 项目 | 是否必须 |
|---|---:|
| 后端可启动 | 是 |
| 前端可启动 | 是 |
| `/api/health` 正常 | 是 |
| `/api/data-sources/status` 正常 | 是 |
| `/api/travel/parse` 正常 | 是 |
| `/api/travel/plan` 正常 | 是 |
| `/api/travel/recalculate` 正常 | 是 |
| `/api/redirect/booking` 正常 | 是 |
| 上海 → 青岛 mock 跑通 | 是 |
| 三张推荐卡展示 | 是 |
| 数据源失败可解释 | 是 |
| LLM 非法输出可降级 | 是 |
| Money 无 float | 是 |
| ErrorResponse 统一 | 是 |
| BLOCKED 不进推荐 | 是 |
| DataSourceMetadata 完整 | 是 |
