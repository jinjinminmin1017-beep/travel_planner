# Architecture

更新日期：2026-07-12

本文记录当前代码中已确认的架构；尚未落地的内容会明确标注为“目标设计，待实现”。

## 前端架构

- 当前前端是 `frontend/` 下的 Expo / React Native App。
- `frontend/index.ts` 使用 `registerRootComponent(App)` 注册 `frontend/src/App.tsx`。
- `frontend/src/App.tsx` 是当前主要 UI 与交互聚合点，包含输入页、结果页、推荐卡、方案详情、数据来源页、异步任务轮询、重算、跳转、反馈和本地留存交互。
- 当前未发现独立路由库；App 内使用底部 tab 状态在“云起”输入与“路明”结果之间切换。
- 当前未发现独立全局状态管理库；运行时状态主要使用 React `useState`、`useEffect`、`useMemo`、`useRef`。
- `frontend/src/api/client.ts` 统一封装 HTTP 请求与错误解析。
- `frontend/src/types/index.ts` 保存前端类型定义。
- `frontend/src/nativeCapabilities.ts` 封装定位授权、外部 URL、分享、复制、最近规划、收藏、提醒和偏好等本地能力。
- `frontend/src/designSystem.ts` 提供颜色、间距、圆角、触控热区和内容宽度等设计常量。

## 后端架构

- 当前后端是 `backend/` 下的 FastAPI 应用。
- `backend/app/main.py` 创建 FastAPI `app`，注册 lifespan、CORS、HTTP middleware、异常处理和全部 API 路由。
- 当前未发现独立 router/controller 注册文件；路由直接写在 `backend/app/main.py`。
- `backend/app/models/schemas.py` 是后端 Pydantic 合同模型中心。
- `backend/app/services/` 是业务服务层：
  - `intent_parser.py`：自然语言输入解析与 TravelRequest 语义校验。
  - `planner.py`：主规划编排、方案构建、失败记录、结果聚合与重算。
  - `candidate_generator.py`：候选方案筛选与排序。
  - `recommendation.py`：LLM 推荐结果校验与三张推荐卡生成。
  - `location_resolver.py`：地点、城市、站点、机场候选解析。
  - `local_transfer_engine.py`：本地接驳段与接驳方式构建。
  - `cost_comfort_risk_engine.py`：费用、舒适度、风险和数据质量计算。
  - `store.py`、`persistence.py`、`cache_store.py`：运行时索引、持久化和 TTL 缓存。
  - `observability.py`：指标快照和事件聚合。
  - `task_queue.py`：异步任务、Provider 超时和并发配置读取。
- `backend/app/data_sources/` 是外部数据源适配层：
  - 配置加载：`config_loader.py`。
  - 地图路线：`map_providers.py`。
  - 地理编码：`geocoding_providers.py`。
  - 铁路：`rail_providers.py`。
  - 航班：`flight_providers.py`。
  - 天气：`weather_providers.py`。
  - LLM：`llm_providers.py`。
  - 跳转：`redirect_providers.py`。
  - 交通目录导入解析：`transport_catalog_providers.py`。
- `backend/app/core/` 提供请求上下文、安全校验和日志配置。

## LLM Prompt 架构边界

- Prompt 设计文档只作为架构约束，不作为运行时 LLM input。
- 运行时 LLM input 由两部分组成：
  - `backend/app/llm/prompts/*.txt` 中对应调用的 system prompt。
  - `backend/app/data_sources/llm_providers.py` 按当前请求拼接的 user prompt。
- Intent Parser Prompt 只解析用户自然语言中的出发地、目的地、日期、时间、偏好、交通方式限制、预算和乘客备注；不得生成车次、航班、票价、余票、候选站点、候选机场、路线方案或推荐方案。
- Recommendation Prompt 只从后端提供的候选摘要中选择 CHEAPEST、MOST_COMFORTABLE、BALANCED 三个 slot；不得生成、补全或修改任何候选方案事实字段。
- Schema 名称如 `TravelRequest Schema V1.16`、`LLMRecommendationOutput Schema V1.16` 只代表后端校验契约。Prompt 中必须提供模型生成 JSON 所需的最小字段契约和关键枚举，不应假设 LLM 天然理解项目内部 Schema。
- Recommendation user prompt 必须单独列出合法 `plan_id` 清单，并要求 AVAILABLE.plan_id 逐字复制该清单中的真实 ID；Prompt 模板不得包含可被模型照抄为真实 `plan_id` 的占位符。
- 完整 `TravelPlan`、完整 JSON Schema、API key、第三方 token、内部成本、实名乘客信息和支付信息不得发送给 LLM。

## 前后端数据流

1. 用户在 App 输入自然语言出行需求。
2. 前端通过 `planTripAsync` 调用 `POST /api/travel/plan/async`。
3. 后端解析输入为 `TravelRequest`，创建 `AsyncJob`，立即返回 RUNNING 状态和 `polling_url`。
4. 前端根据 `async_job.polling_url` 轮询 `GET /api/travel/jobs/{job_id}`。
5. 后端后台任务调用规划链路，返回 `TravelPlanResponse`，其中包含候选方案、推荐结果、数据源元信息、失败说明和用户可见警告。
6. 前端展示推荐卡、候选方案、方案详情、数据状态和数据来源。
7. 用户调整席别、舱位或接驳方式时，前端调用 `POST /api/travel/recalculate`。
8. 用户跳转购票/导航时，前端调用 `POST /api/redirect/booking` 获取 redirect-only URL 或说明。
9. 用户反馈和行为事件分别通过 `POST /api/feedback`、`POST /api/events` 上报。

## 用户流程

- 输入：自然语言描述出发地、目的地、日期、时间约束和偏好。
- 规划中：前端显示异步规划状态，可轮询、重试或取消任务。
- 结果：展示三类推荐卡、候选方案、数据状态、缺失能力和阻断说明。
- 详情：展示时间线、费用、风险、接驳、席别/舱位、来源和可信解释。
- 调整：支持按出发/到达时间重算，支持局部选项重算。
- 跳转：仅生成外部官方或地图跳转，不在本系统内登录、下单、支付或抢票。
- 留存：本地保存最近规划、收藏、提醒和偏好；事件上报不应包含账号、支付、实名或凭证信息。

## 模块职责

- App UI：`frontend/src/App.tsx`。
- API 调用：`frontend/src/api/client.ts`。
- 前端本地能力：`frontend/src/nativeCapabilities.ts`。
- 前端展示格式化：`frontend/src/utils/format.ts`。
- 后端 API 注册：`backend/app/main.py`。
- API 合同：`backend/app/models/schemas.py`、`schemas/*.schema.json`、`frontend/src/types/index.ts`。
- 规划编排：`backend/app/services/planner.py`。
- 数据源适配：`backend/app/data_sources/*_providers.py`。
- 数据源配置：`backend/app/data_sources/config_loader.py` 和 `backend/app/data_sources/data_sources.*.json`。
- 请求上下文、安全与日志：`backend/app/core/`。
- 测试：`backend/app/tests/`。
- 工具脚本：`scripts/`。

## 错误处理策略

- `backend/app/main.py` 使用统一异常处理返回 `ErrorResponse`。
- 请求校验错误返回 `VALIDATION_ERROR` 和 422。
- HTTPException 会被包装为 `HTTP_{status_code}`。
- 未捕获异常返回 `INTERNAL_ERROR` 和用户可见的通用提示。
- HTTP middleware 为响应写入 `x-request-id`、`x-trace-id`、`x-correlation-id`、`x-device-id`。
- 安全策略失败由 `evaluate_request_security` 拦截，并以统一错误结构返回。
- 规划链路使用 `SourceFailure`、`missing_components`、`blocked_plan_types` 和 `missing_plan_explanations` 表达数据源失败或能力缺口。
- 前端 API client 在非 2xx 时读取 `ErrorResponse.user_visible_message` 或 `message` 并抛出 Error。

## 约束无匹配与最近备选架构（V1.16，已实现）

### 已解决的问题

- 约束判断已收敛到 `backend/app/services/constraints/`，规划器与候选生成器统一消费结构化评估结果。
- 真实候选全部违反可放宽硬约束时返回 `planning_status=NO_MATCH`，不再混入系统失败。
- 响应保留最近安全备选、分类型偏差和数据源覆盖范围，可解释“最早几点到”“最低需要多少预算”。
- 分钟、金额、交通方式、换乘和安全要求不可直接换算为一个稳定的通用分数。

### 状态语义

- `COMPLETE`：查询正常完成，存在满足全部硬约束的方案。
- `PARTIAL`：存在满足硬约束的方案，但部分方案族或数据源不可用。
- `NO_MATCH`：查询正常完成，存在可靠候选，但没有候选满足全部硬约束；可返回需用户确认的最近备选。
- `FAILED`：系统异常、核心数据完全不可用，或无法形成任何可验证结论。
- 异步任务计算出 `NO_MATCH` 时，`AsyncJob.job_status` 使用 `COMPLETE`，表示任务正常结束；不得记为任务失败。

### 约束分级

1. 不可放宽约束：安全、合规、无障碍刚需、绝对换乘安全下限、核心事实未验证、`RiskLevel.BLOCKED`。违反后直接排除，不得作为备选。
2. 用户确认后可放宽的硬约束：最晚到达、最早出发、时间窗、预算、允许/排除交通方式、直达要求、换乘次数、指定席位或舱位。违反后只能进入最近备选池。
3. 软偏好：价格、舒适度、少换乘、少步行等。软偏好只影响排序，不应默认排除方案；若用户表达“必须/不能”，Intent Parser 应将其提升为硬约束。

### 分类型约束计算器

统一计算器接口，保留不同偏差单位：

- 时间：分钟及 `EARLIER` / `LATER` 方向。
- 预算：同币种、同 scale 的 `amount_minor` 差值；无法可靠换汇时不得比较。
- 交通方式：新增、缺少或命中排除项的集合，不转换为数值分数。
- 换乘：超出次数；换乘安全先过绝对门禁，再比较缓冲分钟。
- 席位/舱位：请求值与可用替代值，不与时间或金额直接换算。
- 余票、步行和总耗时：分别使用票数、米数和分钟。

每个计算器输出结构化 `ConstraintEvaluation`，至少包含 `constraint_type`、`satisfied`、`relaxation_policy`、`requested_value`、`actual_value`、`deviation`、`reason_code` 和用户可见说明。LLM 不参与硬约束判定、偏差计算或放宽决策。

### 决策流程

1. 规划器生成具有 Provider 核心事实的原始候选。
2. 数据可信度门禁剔除核心事实不完整的候选。
3. 安全/合规门禁剔除不可放宽候选。
4. 约束评估器为每个候选生成分类型偏差向量。
5. 满足全部硬约束的候选进入正常 `plans` 和推荐链路。
6. 正常候选为空时，对可放宽候选执行 Pareto 筛选：若 A 在所有可比偏差上不劣于 B，且至少一项更优，则删除 B。
7. 从 Pareto 前沿按赛道选择最多 3 个代表：`CLOSEST_TO_TIME`、`CLOSEST_TO_BUDGET`、`LEAST_BEHAVIOR_CHANGE`。同一赛道内使用字典序规则，不计算跨单位总分。
8. 返回 `planning_status=NO_MATCH`、`plans=[]`、`recommendation_result=null` 和 `constraint_analysis`。
9. 前端展示“约束未满足”状态；备选必须标记“不满足原始要求”，不得进入正常三张推荐卡、直接购票或 LLM 推荐池。
10. 用户明确接受某个放宽建议后，前端以调整后的 `TravelRequest` 重新调用规划接口；只有新请求满足约束的方案才能进入正常结果。

### 赛道内排序

采用确定性字典序：

1. 不可放宽约束违反数必须为 0。
2. 被放宽的显式硬约束种类越少越好。
3. 优先保留用户明确表达的高优先级约束。
4. 比较当前赛道的同类型偏差。
5. 数据质量越高越好。
6. 风险越低越好。
7. 最后比较软偏好。

跨类型方案不选“总冠军”。例如“晚到 10 分钟且不超预算”和“按时但超预算 20 元”应作为两个取舍并列展示，除非用户已经明确时间或预算优先级。

### 数据覆盖与结论边界

- Provider 查询成功且返回空结果时可以说“未找到”。
- Provider 超时或失败时只能说“暂时无法确认”。
- Provider 未启用时必须说明“该交通方式未覆盖”。
- 只有相关交通方式均为 `VERIFIED` 时才能声称“全交通方式最早/最低”；否则只能说“当前已验证铁路方案中最早”等受限结论。

### 目标模块边界

约束规则从 `planner.py` 和 `candidate_generator.py` 收敛到 `backend/app/services/constraints/`：

- `models.py`：内部评估模型。
- `evaluator.py`：统一执行计算器。
- `time_calculator.py`、`budget_calculator.py`、`transport_mode_calculator.py`、`seat_cabin_calculator.py`：分类型偏差计算。
- `safety_gate.py`：不可放宽门禁。
- `pareto.py`：Pareto 支配筛选。
- `relaxation_selector.py`：分赛道选择最近备选。

`planner.py` 只负责编排，`candidate_generator.py` 只消费已满足硬约束的候选。第一期不引入数据库迁移；`constraint_analysis` 随 `TravelPlanResponse` 使用现有持久化 JSON 保存。

### 影响范围

- 后端：Schema、规划编排、候选过滤、异步任务状态映射、持久化索引和可观测性。
- 前端：类型定义、轮询完成判断、`NO_MATCH` 页面、备选详情、确认放宽后重新规划。
- API：`TravelPlanResponse` 已增加 `constraint_analysis`，`PlanningStatus` 已增加 `NO_MATCH`，schema version 为 `1.16`。
- 可观测性：新增 `PLANNING_NO_MATCH` 业务事件，不能混入系统失败或普通规划成功指标。
- 测试：分类型计算器、安全门禁、Pareto、覆盖范围文案、同步/异步接口和前端空态。

### 风险与回滚

- 风险：把软偏好误当硬约束、把未覆盖 Provider 误报为无方案、备选进入正常推荐池、Pareto 前沿过大、前后端对新枚举处理不一致。
- 控制：计算器使用确定性规则；备选上限为 3；合同测试校验 `NO_MATCH` 不含正常推荐；日志记录过滤前后数量、违反原因和 coverage，不记录敏感信息。
- 回滚：保留现有 `FAILED + missing_plan_explanations` 路径作为功能开关关闭后的行为；关闭约束分析功能时不生成 `constraint_analysis`，不影响正常 `COMPLETE/PARTIAL` 方案链路。

## 后续扩展方式

- 新 API：优先在 `backend/app/models/schemas.py` 定义请求/响应模型，再在 `backend/app/main.py` 注册路由，并同步前端 `frontend/src/api/client.ts` 与 `frontend/src/types/index.ts`。
- 新数据源：新增或扩展 `backend/app/data_sources/*_providers.py`，在 `data_sources.*.json` 和 `.env.example` 增加配置，并补充 Provider 测试。
- 新规划能力：优先接入 `planner.py` 编排，必要时拆分到 `services/` 独立模块，并补充 schema、测试和数据源失败语义。
- 前端拆分：当前 `App.tsx` 较集中；后续可按“输入、规划状态、结果概览、方案详情、数据来源、反馈”等边界抽出组件，但需要同步更新本索引。
- 合同变更：运行 `scripts/export_schemas.py`，检查 `schemas/` diff，并同步前端类型。

## 当前边界

- 当前没有独立 Web 前端交付路线。
- 当前没有独立后端 routers/controllers 分层。
- 当前没有前端路由库或全局状态库。
- 当前接口文档只记录代码中已发现的接口。
