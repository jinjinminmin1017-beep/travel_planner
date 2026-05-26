# AI Travel Planner App Development Execution Plan for Codex

版本：V1  
用途：供 Codex 按顺序执行开发任务  
范围：Web App first，后续 App later  

基准文档：

- PRD：AI Travel Planner PRD V2.1
- 系统架构设计：AI Travel Planner System Architecture V1.1
- 核心数据结构与 JSON Schema：AI_Travel_Planner_Data_Schema_V1.15
- 数据源准入规范：AI_Travel_Planner_Data_Source_Governance_V1.1
- LLM Prompt 设计：AI_Travel_Planner_LLM_Prompt_Design_V1
- Codex 开发任务拆解：AI_Travel_Planner_Codex_Task_Breakdown_V1

---

## 1. 执行原则

Codex 必须严格遵守以下原则：

1. 以 `AI_Travel_Planner_Data_Schema_V1.15` 为唯一数据契约。
2. 第一阶段只实现 Web App，不实现 App。
3. 第一阶段只使用 mock 数据，不接真实数据源。
4. 不允许接入未知数据源、逆向接口、无授权接口。
5. 不允许逆向 12306。
6. 不允许绕过验证码、登录态或风控。
7. 不允许自动抢票、自动下单、自动支付。
8. LLM 不得生成事实数据。
9. LLM 只能用于自然语言解析、候选方案选择和解释。
10. 所有 LLM 输出必须经过 Schema 校验和 Semantic Validator。
11. 所有金额必须使用 `Money` 或 `MoneyDelta`，不得使用 float/number 表示金额。
12. 所有 API 错误必须返回 `ErrorResponse`。
13. 所有用户可见事实字段必须携带 `DataSourceMetadata`。
14. BLOCKED 方案不得进入 LLM 推荐候选池。
15. `DataSourceConfig` 不得直接暴露给前端状态接口。
16. `/api/data-sources/status` 必须返回 `DataSourceRuntimeStatus`。

---

## 2. 总体开发顺序

Codex 按以下顺序执行：

```text
Phase 0：开发准备
Phase 1：项目骨架
Phase 2：Schema / 数据模型
Phase 3：Mock 数据源
Phase 4：后端核心 API
Phase 5：核心规划引擎
Phase 6：LLM 调用与降级
Phase 7：前端 Web App
Phase 8：上海 → 青岛端到端验证
Phase 9：真实数据源接入准备
Phase 10：生产化增强准备
Phase 11：后续 App 化准备
```

---

## 3. Phase 0：开发准备

### 3.1 目标

创建项目基础结构，并把所有设计文档放入项目中，作为 Codex 开发输入。

### 3.2 必须创建的目录

```text
ai-travel-planner/
  README.md
  docs/
  schemas/
  backend/
  frontend/
  mock_data/
  scripts/
  tests/
```

### 3.3 必须放入 docs 的文档

```text
docs/
  PRD.md
  SYSTEM_ARCHITECTURE.md
  DATA_SCHEMA.md
  DATA_SOURCE_GOVERNANCE.md
  LLM_PROMPT_DESIGN.md
  CODEX_TASK_BREAKDOWN.md
  APP_DEVELOPMENT_EXECUTION_PLAN.md
```

### 3.4 验收标准

1. 项目目录结构完整。
2. README 说明项目目标、启动方式和当前开发阶段。
3. docs 中包含所有基准文档。
4. 不包含任何真实 API key、token、账号或密码。

---

## 4. Phase 1：项目骨架

### 4.1 后端项目骨架

创建 FastAPI 后端项目。

推荐结构：

```text
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
```

### 4.2 前端项目骨架

创建 React + TypeScript Web App。

推荐结构：

```text
frontend/
  src/
    api/
    components/
    pages/
    types/
    stores/
    utils/
    mock/
```

### 4.3 首批 API

先实现：

```text
GET /api/health
GET /api/data-sources/status
```

### 4.4 验收标准

1. 后端可启动。
2. 前端可启动。
3. `/api/health` 返回 `HealthResponse`。
4. `/api/data-sources/status` 返回 `DataSourceStatusResponse`。
5. 所有错误路径返回 `ErrorResponse`。
6. 所有响应包含 `schema_version = 1.15`。

---

## 5. Phase 2：Schema / 数据模型

### 5.1 后端 Pydantic Models

必须实现以下模型：

```text
Money
MoneyDelta
TimePoint
GeoPoint
NormalizedScores
CacheMetadata
DataSourceMetadata
DataSourceConfig
DataSourceRuntimeStatus
SourceFailure
ErrorResponse
TravelHardConstraints
TravelSoftPreferences
TravelRequest
ParseTravelRequestResponse
StationCandidate
AirportCandidate
SeatOption
CabinOption
RailSegment
FlightSegment
LocalTransferSegment
TicketEnhancement
CostBreakdown
ComfortScore
RiskItem
RiskAssessment
DataQuality
BookingRedirect
TravelPlan
TravelPlanResponse
GetTravelPlanResponse
LLMRecommendationInput
LLMRecommendationOutput
RecommendationSlot
RecommendationResult
LLMValidationResult
RecalculateRequest
SelectedOption
RecalculateResponse
RecalculateChangeSummary
BookingRedirectRequest
BookingRedirectResponse
HealthResponse
DataSourceStatusResponse
```

### 5.2 前端 TypeScript Types

必须创建与后端一致的 TypeScript 类型：

```text
TravelRequest
TravelPlanResponse
TravelPlan
RailSegment
FlightSegment
LocalTransferSegment
RecommendationSlot
CostBreakdown
ComfortScore
RiskAssessment
DataQuality
SourceFailure
ErrorResponse
RecalculateRequest
RecalculateResponse
BookingRedirectRequest
BookingRedirectResponse
```

### 5.3 Schema 约束

1. `Money` 必须使用 `amount_minor + currency + scale`。
2. `MoneyDelta` 允许负数。
3. 时间字段使用 `TimePoint`。
4. 核心对象必须禁止 unknown fields。
5. 所有金额字段不得使用 float。
6. `SourceFailure` 必须包含 `failure_id`。
7. `TravelPlan` 必须包含 `recommendation_eligibility / can_be_selected_by_llm / block_reason_code / block_reason_message`。
8. `LLMRecommendationOutput` 不得包含 `candidate_plan_ids`。
9. `LLMRecommendationInput` 必须包含 `candidate_plan_ids`。
10. `RecalculateRequest.selected_option` 必须包含 `option_type / option_id / option_value / source_option_version`。

### 5.4 验收标准

1. Pydantic models 与 Schema V1.15 对齐。
2. TypeScript types 与 API 响应一致。
3. 单元测试覆盖 Money、TimePoint、ErrorResponse、SourceFailure。
4. 不合法金额、未知字段、缺少 required 字段均能被拦截。
5. LLM 输出结构能被 Schema 校验。

---

## 6. Phase 3：Mock 数据源

### 6.1 DataSourceConfig Loader

实现数据源配置读取：

```text
backend/app/data_sources/config_loader.py
backend/app/data_sources/data_sources.dev.json
backend/app/data_sources/data_sources.test.json
backend/app/data_sources/data_sources.prod.json
```

### 6.2 Mock Adapter

实现以下 mock adapter：

```text
MockMapDataProvider
MockRailDataProvider
MockFlightDataProvider
MockTaxiEstimateProvider
MockBookingRedirectProvider
MockLLMProvider
```

### 6.3 Mock 数据场景

必须覆盖上海 → 青岛：

```text
上海嘉定南翔格林公馆
上海虹桥站
上海虹桥机场
上海浦东机场
青岛北站
青岛胶东机场
青岛金水假日酒店
```

必须支持：

```text
高铁直达
高铁中转
航班直飞
航班中转
航班 + 高铁混合
高铁票源增强 S 档
高铁票源增强 A 档
买短补长高风险
数据源 fallback
前序航班缺失
高铁余票缺失
安全关键数据缺失 BLOCKED
```

### 6.4 验收标准

1. 所有 mock 输出符合 Schema V1.15。
2. 所有事实字段携带 `DataSourceMetadata`。
3. 数据源失败时生成 `SourceFailure`。
4. 安全关键失败时生成 `blocked_plan_types`。
5. mock 数据不得模拟成真实官方数据源。
6. mock 数据源只允许用于 DEV / TEST。

---

## 7. Phase 4：后端核心 API

### 7.1 必须实现的 API

```text
GET /api/health
GET /api/data-sources/status
POST /api/travel/parse
POST /api/travel/plan
GET /api/travel/plans/{plan_id}
POST /api/travel/recalculate
POST /api/redirect/booking
```

### 7.2 API 验收标准

1. `/api/health` 返回 `HealthResponse`。
2. `/api/data-sources/status` 返回 `DataSourceStatusResponse`，且不返回 `DataSourceConfig[]`。
3. `/api/travel/parse` 返回 `ParseTravelRequestResponse`。
4. `/api/travel/plan` 返回 `TravelPlanResponse`。
5. `/api/travel/plans/{plan_id}` 返回 `GetTravelPlanResponse`。
6. `/api/travel/recalculate` 返回 `RecalculateResponse`。
7. `/api/redirect/booking` 返回 `BookingRedirectResponse`。
8. 所有 4xx / 5xx 返回 `ErrorResponse`。
9. 所有响应透传 `request_id / trace_id / correlation_id / idempotency_key`。
10. 不包含真实交易、登录、下单、支付能力。

---

## 8. Phase 5：核心规划引擎

### 8.1 必须实现的模块

```text
Travel Planning Orchestrator
Location Resolver
Station Candidate Generator
Airport Candidate Generator
Local Transfer Engine
Rail Planning Engine
Flight Planning Engine
Ticket Enhancement Engine
Candidate Plan Generator
Cost Calculator
Comfort Scoring Engine
Risk Assessment Engine
Deterministic Rule Engine
Result Composer
```

### 8.2 关键规则

1. LocalTransferSegment 字段必须对齐：origin、destination、transfer_mode、distance_meters、duration_minutes、estimated_cost、traffic_risk、walking_distance_meters、data_source、redirect_info。
2. Rail Planning Engine 必须支持 DIRECT_RAIL、TRANSFER_RAIL、MULTI_TRANSFER_RAIL、RAIL_TICKET_ENHANCEMENT。
3. Flight Planning Engine 必须支持 DIRECT_FLIGHT、TRANSFER_FLIGHT、MULTI_AIRPORT_FLIGHT、FLIGHT_RAIL_MIXED。
4. Ticket Enhancement Engine 必须实现 S / A / NOT_RECOMMENDED / BLOCKED。
5. Cost Calculator 必须使用 Money / MoneyDelta，不得使用 float。
6. ComfortScore breakdown 0–10，score_vector 使用 NormalizedScores。
7. RiskAssessment 必须结构化 RiskItem。
8. Deterministic Rule Engine 必须在 LLM 前过滤 BLOCKED / EXPIRED / INVALIDATED / can_be_selected_by_llm=false 的方案。

### 8.3 验收标准

1. 可生成门到门 TravelPlan。
2. 可生成高铁、航班、接驳、混合交通、票源增强方案。
3. hard_constraints 被严格执行。
4. 数据源失败可生成 SourceFailure。
5. 安全关键失败可阻断推荐。
6. 被阻断方案可被前端解释。

---

## 9. Phase 6：LLM 调用与降级

### 9.1 必须实现

```text
Intent Parser Prompt
Recommendation Prompt
Repair Prompt
Schema Validator
Semantic Validator
Deterministic Fallback
LLMValidationResult
LLM call logging
```

### 9.2 Intent Parser 规则

1. 输出 TravelRequest。
2. 不得生成车次、航班、价格、余票、路线方案、推荐方案。
3. 输出必须通过 Schema 校验和 Semantic Validator。

### 9.3 Recommendation 规则

1. 输入 LLMRecommendationInput。
2. 输出 LLMRecommendationOutput。
3. 只能选择 candidate_plan_ids 内的 plan_id。
4. 不得选择 BLOCKED。
5. 不得选择 can_be_selected_by_llm = false。
6. 不得选择 EXPIRED / INVALIDATED。
7. 不得修改事实字段。
8. 必须输出三张推荐卡。
9. 无方案时输出 NOT_AVAILABLE 或 BLOCKED。

### 9.4 Repair / Fallback 规则

1. Repair 最多一次。
2. Repair 失败进入 Deterministic Fallback。
3. Fallback 仍必须输出三卡位模型。
4. Fallback reason 使用模板，不使用 LLM 自由生成。

### 9.5 验收标准

1. LLM 输出不存在 plan_id 能拦截。
2. LLM 选择 BLOCKED 能拦截。
3. LLM 少一个推荐卡能 repair。
4. repair 失败后 fallback。
5. fallback 仍输出三卡位。
6. 日志记录 prompt_version / model_name / latency / final_strategy。

---

## 10. Phase 7：前端 Web App

### 10.1 页面

```text
首页输入页
规划中页面
结果页三卡
方案详情页 / 弹窗
数据源状态页
错误页
```

### 10.2 必须展示

1. 自然语言输入。
2. planning_status。
3. progress。
4. missing_components。
5. user_visible_warnings。
6. 三张推荐卡。
7. NOT_AVAILABLE 原因。
8. BLOCKED 原因。
9. 门到门时间线。
10. 费用明细。
11. 舒适度评分拆解。
12. 风险项。
13. 数据质量。
14. 数据来源和更新时间。
15. 座席切换。
16. 舱位切换。
17. 接驳方式切换。
18. 跳转按钮。

### 10.3 交互规则

1. 只能选择后端返回的 option_id。
2. 切换座席/舱位/接驳方式时调用 `/api/travel/recalculate`。
3. 使用 `RecalculateChangeSummary` 更新 UI。
4. 点击跳转前调用 `/api/redirect/booking`。
5. url_available = false 时展示 fallback_instruction。
6. 不展示自动抢票、下单、支付文案。

---

## 11. Phase 8：上海 → 青岛端到端验证

### 11.1 测试输入

```text
我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。
```

### 11.2 必须验证

1. 最便宜：打车 + 高铁 + 打车。
2. 最舒适：打车 + 航班 + 打车。
3. 综合推荐：解释费用、耗时、风险、舒适度取舍。
4. 高铁中转方案。
5. 航班中转方案。
6. 票源增强 S/A。
7. 买短补长高风险备选，不进主推荐。
8. 数据源失败降级场景。
9. LLM 非法输出 repair/fallback。
10. 座席/舱位切换重算。
11. mock 跳转。

### 11.3 验收标准

1. 一条用户输入完成端到端。
2. 前端展示三卡。
3. 后端响应符合 Schema V1.15。
4. LLM 非法输出可 repair/fallback。
5. 数据源失败可解释。
6. BLOCKED 不进入推荐。
7. trace_id 可追踪。

---

## 12. Phase 9：真实数据源接入准备

真实数据源不在第一阶段立即接入。

后续接入顺序：

```text
1. 地图数据源
2. 地址解析
3. 本地接驳路线
4. 高铁站点 / 时刻
5. 高铁票价 / 余票
6. 航班计划
7. 航班动态
8. 航班价格
9. 跳转购票
10. 打车平台跳转
```

每接一个真实数据源，必须：

1. 更新 DataSourceConfig。
2. 完成商务 Review。
3. 增加 fallback。
4. 增加 SourceFailure 测试。
5. 增加 DataSourceRuntimeStatus。
6. 增加前端数据来源展示。
7. 确认 license_status = APPROVED。
8. 确认 commercial_allowed = true。
9. 确认 PROD 环境 enabled。

---

## 13. Phase 10：生产化增强准备

后续补充：

1. 数据库持久化。
2. Redis 缓存。
3. 异步 job。
4. WebSocket / polling。
5. 日志系统。
6. 监控系统。
7. API 限流。
8. 错误告警。
9. LLM 成本控制。
10. 用户反馈。
11. 安全审计。
12. 部署脚本。
13. CI/CD。

---

## 14. Phase 11：后续 App 化准备

App 不重写后端，复用现有 API：

```text
/api/travel/parse
/api/travel/plan
/api/travel/recalculate
/api/redirect/booking
/api/data-sources/status
/api/health
```

后续 App 增加：

1. 用户登录。
2. 行程收藏。
3. 历史行程。
4. 价格/余票提醒。
5. 出发提醒。
6. 延误提醒。
7. 推送通知。
8. 地图 App 深度跳转。
9. App 原生分享。
10. 用户偏好记忆。

---

## 15. 第一阶段完成定义

第一阶段必须满足：

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
12. LLM 输出非法可 repair/fallback。
13. 前端可展示三卡和详情。
14. 可切换座席、舱位、接驳方式并重算。
15. 可展示数据源。
16. 可展示失败原因。
17. 可触发 mock 跳转。
18. 所有金额使用 Money。
19. 所有错误使用 ErrorResponse。
20. 所有事实字段携带 DataSourceMetadata。

---

## 16. Codex 禁止事项

Codex 禁止：

1. 调用未知真实接口。
2. 调用逆向 12306。
3. 抓取第三方网页。
4. 绕过验证码。
5. 绕过登录态。
6. 自动抢票。
7. 自动下单。
8. 自动支付。
9. 把 LLM 当事实源。
10. 让 LLM 生成 TravelPlan。
11. 让 LLM 修改候选方案。
12. 使用 float 计算金额。
13. 直接返回临时错误结构。
14. 暴露 DataSourceConfig 给前端状态接口。
15. 跳过 Semantic Validator。
16. 跳过 DataSourceConfig 校验。
17. 在 PROD 启用 mock 数据。
18. 在 PROD 启用 PENDING_REVIEW 数据源。

---

## 17. Codex 第一轮执行范围

第一轮只执行：

```text
Phase 0：开发准备
Phase 1：项目骨架
Phase 2：Schema / 数据模型
```

第一轮不要做：

1. 完整规划引擎。
2. 复杂前端页面。
3. 真实数据源接入。
4. App。
5. 自动下单。
6. 支付。
7. 抢票。

第一轮验收后，再进入 Phase 3 和 Phase 4。
