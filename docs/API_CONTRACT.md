# API Contract

更新日期：2026-08-16

本文只记录已在 `backend/app/main.py` 或 `frontend/src/api/client.ts` 中发现的接口。统一错误结构见 `backend/app/models/schemas.py` 的 `ErrorResponse`。

当前 API schema version 为 `1.18`；V1.18 仅新增 `DataSourceType=OTA` 与 `redirect_type=FLIGGY`，规划请求结构不变。

## 通用错误响应

- Response：`ErrorResponse`
- 字段：`schema_version`、`request_id`、`error_code`、`message`、`user_visible_message`、`retryable`、`details`、`generated_at`
- 典型状态码：400、404、422、429、500
- 后端位置：`backend/app/main.py` 的 `error_payload`、异常处理器和安全 middleware
- 前端处理：`frontend/src/api/client.ts` 的 `request<T>()`

## GET /api/health

- Method：GET
- URL：`/api/health`
- Request：无 body。
- Response：`HealthResponse`
- Error Response：通用 `ErrorResponse`
- 前端调用位置：未发现前端调用。
- 后端实现位置：`backend/app/main.py` `health()`

## GET /api/data-sources/status

- Method：GET
- URL：`/api/data-sources/status`
- Request：无 body。
- Response：`DataSourceStatusResponse`
- Error Response：通用 `ErrorResponse`
- 前端调用位置：`frontend/src/api/client.ts` `loadDataSources()`；当前未发现 `App.tsx` 调用。
- 后端实现位置：`backend/app/main.py` `data_sources_status()`

## GET /api/admin/data-sources

- Method：GET
- URL：`/api/admin/data-sources`
- Request：无 body。
- Response：`DataSourceStatusResponse`
- Error Response：通用 `ErrorResponse`
- 前端调用位置：未发现前端调用。
- 后端实现位置：`backend/app/main.py` `admin_data_sources_status()`

## GET /api/observability/metrics

- Method：GET
- URL：`/api/observability/metrics`
- Request：无 body。
- Response：`metrics_snapshot()` 返回的指标快照。
- Error Response：通用 `ErrorResponse`
- 前端调用位置：未发现前端调用。
- 后端实现位置：`backend/app/main.py` `observability_metrics()`

## POST /api/travel/parse

- Method：POST
- URL：`/api/travel/parse`
- Request：`ParseTravelRequestBody`，包含 `raw_user_input`。
- Response：`ParseTravelRequestResponse`
- Error Response：通用 `ErrorResponse`；解析需补充信息时返回 `PARSE_NEEDS_INPUT`。
- 前端调用位置：未发现前端调用。
- 后端实现位置：`backend/app/main.py` `parse_travel()`

### 相对日期与时间解析语义（无字段变更，2026-08-16 已实现）

- 后端以 `Asia/Shanghai` 的带时区当前时刻作为国内规划的权威解析基准，不信任客户端时钟。
- 应确定性支持今天、明天、后天、本周几/这周几、下周几/下星期几、最近的周几、“N 小时后”，以及与出发动作绑定的“现在就要出发、现在出发、马上/立即/即刻/尽快出发”；跨午夜时同时更新 `travel_date` 和对应 `TimePoint`。
- 立即出发语义必须在请求开始时只捕获一次权威 `current_datetime`，返回 `travel_date=<上海当天>`、`time_anchor_type=DEPARTURE`、`earliest_departure_time=current_datetime`、`time_window_start=current_datetime`、`time_window_end=null`；两个 TimePoint 必须完全相同。仅表示对话时刻的“现在”（例如“我现在想规划明天出发”）不得覆盖明确的未来日期。
- `travel_date` 必须归一化为 `YYYY-MM-DD`；具体时间必须使用现有 `TimePoint` 结构，不返回裸时间字符串。
- “这个周末”“月底”等无法唯一映射到单个日期的表达返回 HTTP 400 + `PARSE_NEEDS_INPUT`，`details.missing_fields` 包含 `travel_date`，`details.follow_up_questions` 提供针对性问题，不得只返回通用解析失败。
- LLM 输出格式非法但原始输入包含可确定日期或立即出发语义时，后端必须使用确定性解析恢复，不得把格式错误误报为信息缺失；该规则也适用于 LLM 与 repair 都返回 `null`、中文相对词、完整 datetime 或其他非法 `travel_date` 的情况。
- 明确解析到过去日期时返回可解释校验错误，不得向票务 Provider 发起过去日期查询。
- 本规则同时适用于 `POST /api/travel/plan` 与 `POST /api/travel/plan/async` 内部的自然语言解析阶段；结构化 `travel_request` 路径保持现有校验。

## POST /api/travel/plan

- Method：POST
- URL：`/api/travel/plan`
- Request：`PlanRequest`，包含 `raw_user_input` 或 `travel_request`。
- Response：`TravelPlanResponse`
- Error Response：通用 `ErrorResponse`；解析需补充信息时返回 `PARSE_NEEDS_INPUT`；非法输入可能返回 400。
- 前端调用位置：`frontend/src/api/client.ts` `planTrip()`；当前未发现 `App.tsx` 调用。
- 后端实现位置：`backend/app/main.py` `plan_travel()`

## POST /api/travel/plan/async

- Method：POST
- URL：`/api/travel/plan/async`
- Request：`PlanRequest`；前端传字符串时 body 为 `{ "raw_user_input": string }`，传结构化请求时 body 为 `{ "travel_request": TravelRequest }`。
- Response：`TravelPlanResponse`，通常包含 `async_job`、`planning_status=RUNNING`、`polling_url`。
- Error Response：通用 `ErrorResponse`；解析需补充信息时返回 `PARSE_NEEDS_INPUT`；非法输入可能返回 400。
- 前端调用位置：`frontend/src/api/client.ts` `planTripAsync()`；`frontend/src/App.tsx` 提交输入和重按时间规划时调用。
- 后端实现位置：`backend/app/main.py` `plan_travel_async()`

## GET /api/travel/jobs/{job_id}

- Method：GET
- URL：`/api/travel/jobs/{job_id}`
- Request：path 参数 `job_id`。
- Response：`TravelPlanResponse`
- Error Response：通用 `ErrorResponse`；任务不存在或过期返回 404。
- 前端调用位置：`frontend/src/api/client.ts` `pollPlanningJob()`；`frontend/src/App.tsx` 轮询异步任务。
- 后端实现位置：`backend/app/main.py` `get_planning_job()`

### 异步观察与渐进结果契约（V1.17，无字段变更，已实现）

- `planning_status=PENDING/RUNNING` 且 `async_job.job_status=QUEUED/RUNNING/WAITING_SOURCE` 表示服务端任务仍在活动。此时 `plans=[]` 是 loading 快照，不是“没有方案”。
- 活动态允许返回非空 `plans`，但每个计划都必须是已通过安全门禁的完整门到门方案；前端可以立即展示，同时继续轮询。活动态的 `recommendation_result` 可以为 `null`，前端不得自行补推荐结论。
- 每次新快照的 `progress` 不得下降，`async_job.updated_at` 必须反映最近一次有效状态或结果更新。
- 服务端终态由 `planning_status=COMPLETE/PARTIAL/NO_MATCH/FAILED` 与对应终态 `async_job.job_status` 表达。客户端轮询次数耗尽、App 进入后台或单次 GET 失败都不得被解释为服务端终态。
- 客户端本地观察窗口耗尽时必须保留 `job_id`、`polling_url` 和最后响应，展示“仍在规划/继续获取”；恢复时先 GET 同一个 job。不得仅因 `plans.length === 0` 展示普通空态，也不得创建重复规划任务。
- `NO_MATCH` 继续使用独立约束无匹配页面；`FAILED` 使用失败与重试页面。普通“暂无可用方案”不能承载任何活动态响应。
- 本规则复用现有 `TravelPlanResponse`、`AsyncJob` 和 GET endpoint，不提升 schema version，不增加数据库迁移。

## POST /api/travel/jobs/{job_id}/retry

- Method：POST
- URL：`/api/travel/jobs/{job_id}/retry`
- Request：path 参数 `job_id`，无 body。
- Response：`TravelPlanResponse`
- Error Response：通用 `ErrorResponse`；任务不存在或过期返回 404。
- 前端调用位置：`frontend/src/api/client.ts` `retryPlanningJob()`；`frontend/src/App.tsx` 重试失败数据来源。
- 后端实现位置：`backend/app/main.py` `retry_planning_job()`

## POST /api/travel/jobs/{job_id}/cancel

- Method：POST
- URL：`/api/travel/jobs/{job_id}/cancel`
- Request：path 参数 `job_id`，无 body。
- Response：`TravelPlanResponse`
- Error Response：通用 `ErrorResponse`；任务不存在或过期返回 404。
- 前端调用位置：`frontend/src/api/client.ts` `cancelPlanningJob()`；`frontend/src/App.tsx` 取消当前规划。
- 后端实现位置：`backend/app/main.py` `cancel_planning_job()`

## GET /api/travel/plans/{plan_id}

- Method：GET
- URL：`/api/travel/plans/{plan_id}`
- Request：path 参数 `plan_id`。
- Response：`GetTravelPlanResponse`
- Error Response：通用 `ErrorResponse`；方案不存在或过期返回 404。
- 前端调用位置：未发现前端调用。
- 后端实现位置：`backend/app/main.py` `get_travel_plan()`

## POST /api/travel/recalculate

- Method：POST
- URL：`/api/travel/recalculate`
- Request：`RecalculateRequest`
- Response：`RecalculateResponse`
- Error Response：通用 `ErrorResponse`；方案不存在返回 404；非法重算请求返回 400。
- 前端调用位置：`frontend/src/api/client.ts` `recalculate()`；`frontend/src/App.tsx` 调整席别、舱位、本地接驳和时间重算后替换方案。
- 后端实现位置：`backend/app/main.py` `recalculate()`

### 结果集席别重算契约（V1.17，已实现）

现有 V1.16 的 `recalculate_scope=PLAN_AND_RECOMMENDATION` 只表示是否重新计算推荐，不表示把选择应用到其他计划。V1.17 增加独立字段：

```json
{
  "plan_id": "plan_a",
  "change_type": "SEAT_TYPE",
  "target_segment_id": "rail_a",
  "selected_option": {
    "option_type": "SEAT",
    "option_id": "seat_a_first",
    "option_value": "一等座",
    "source_option_version": "ui_selected"
  },
  "application_scope": "RESULT_SET",
  "recalculate_scope": "FULL_REEVALUATION"
}
```

- `application_scope`：`TARGET_PLAN | RESULT_SET`，默认 `TARGET_PLAN` 以兼容旧客户端。
- `SEAT_TYPE + RESULT_SET`：以后端从目标段 option_id 解析出的 `seat_type` 为准，仅应用到同一结果集中 `train_number` 与目标段相同的铁路段。
- 不包含目标车次的计划保持原席别、费用和推荐资格，不得因为本次席别调整退出推荐。
- 同一计划包含其他车次时，其他车次保持原席别；不得把一次车次席别调整提升为全行程统一席别。
- `LOCAL_TRANSFER_MODE` 第一阶段只允许 `TARGET_PLAN`；非法组合返回 422 `VALIDATION_ERROR`。
- 前端不得假设同一车次在不同计划中具有相同 option_id；后端必须按每个匹配段自己的 seat_options 解析合法 option_id 和价格。

`RecalculateResponse` 保留现有 `plan` 作为兼容字段，并增加：

```json
{
  "plan": {},
  "updated_response": {},
  "preference_application": {
    "preference_type": "RAIL_SEAT",
    "canonical_value": "一等座",
    "application_scope": "RESULT_SET",
    "applied_plan_ids": ["plan_a", "plan_b"],
    "unsupported_plan_ids": [],
    "message": "G56 的一等座已同步到2个方案。"
  },
  "recommendation_result": {}
}
```

合同约束：

- `RESULT_SET` 时 `updated_response` 和 `preference_application` 必须非空；`updated_response.plans` 是完整替换快照，不是增量 patch。
- 本操作是车次级结果集同步，不得改写全局 `updated_response.travel_request.preferred_rail_seat` 或 `preference_source`。
- `applied_plan_ids` 中的计划必须包含目标车次，且该计划内所有同车次铁路段所选席别都匹配 `canonical_value`；其他车次不受影响。
- `unsupported_plan_ids` 只允许包含“存在目标车次但该段没有目标席别”的计划；不包含目标车次的计划不得进入该列表，也不得因此失去 AVAILABLE 推荐资格。
- `updated_response.recommendation_result` 与顶层 `recommendation_result` 必须一致；后续版本可弃用重复的顶层字段，但 V1.17 保留兼容。
- 后端必须先完成整组验证再持久化；失败时不允许留下部分计划已更新的状态。
- 幂等键命中时返回同一完整结果集版本。

Loading 行为：前端保留当前门到门结果并显示局部更新态；成功后整体替换结果集，失败时继续显示旧快照并提示调整失败。

Empty 行为：目标段 option_id 在请求时已校验为可用，因此至少目标计划应能完成同步；若目标快照已过期或 option_id 不存在，返回明确的 400 错误并保留旧快照，不得产生全局 NOT_AVAILABLE 假结果。

## POST /api/redirect/booking

- Method：POST
- URL：`/api/redirect/booking`
- Request：`BookingRedirectRequest`
- Response：`BookingRedirectResponse`
- Error Response：通用 `ErrorResponse`；方案不存在返回 404；FLIGGY 跳转的 segment 归属、HTTPS host allowlist 或持久化数据校验失败返回 400。
- `BookingRedirectRequest` 不接受 URL。`redirect_type=FLIGGY` 时必须提供 `plan_id` 与 `segment_id`，服务端只从持久化计划的 `booking_redirects` 读取响应 `jumpUrl`。
- FLIGGY redirect 必须与生成它的 plan/segment binding 一致且未过期；不可用时返回手动打开飞猪核价说明，不回退到航司或 12306。
- 前端调用位置：`frontend/src/api/client.ts` `bookingRedirect()`；铁路与航班 CTA 统一为“去飞猪核价并预订”。
- 后端实现位置：`backend/app/main.py` `booking_redirect()`；跳转生成与校验在 `backend/app/data_sources/redirect_providers.py`。

## POST /api/feedback

- Method：POST
- URL：`/api/feedback`
- Request：`FeedbackRequest`
- Response：`FeedbackResponse`
- Error Response：通用 `ErrorResponse`；反馈包含账号、支付、实名或凭证信息时返回 400。
- 前端调用位置：`frontend/src/api/client.ts` `submitFeedback()`；`frontend/src/App.tsx` 方案详情反馈入口。
- 后端实现位置：`backend/app/main.py` `submit_feedback()`

## POST /api/events

- Method：POST
- URL：`/api/events`
- Request：`AppEventRequest`
- Response：`AppEventResponse`
- Error Response：通用 `ErrorResponse`；metadata 包含账号、支付、实名或凭证信息时返回 400。
- 前端调用位置：`frontend/src/api/client.ts` `trackEvent()`；`frontend/src/App.tsx` 输入、规划结果、推荐点击、跳转、反馈、收藏、提醒、偏好等事件。
- 后端实现位置：`backend/app/main.py` `submit_app_event()`；事件聚合在 `backend/app/services/observability.py`

## 约束无匹配契约（V1.16，已实现）

### 适用接口

以下接口统一返回扩展后的 `TravelPlanResponse`：

- `POST /api/travel/plan`
- `POST /api/travel/plan/async`
- `GET /api/travel/jobs/{job_id}`
- `POST /api/travel/jobs/{job_id}/retry`

Request、Query Params 和 HTTP Error Response 保持现有定义。`NO_MATCH` 是 HTTP 200 的业务结果，不得转换为 4xx/5xx。

### PlanningStatus

V1.16 增加：

```txt
NO_MATCH
```

- `NO_MATCH`：规划正常完成，但没有候选满足全部硬约束，且存在可解释的约束分析或最近备选。
- 异步结果为 `NO_MATCH` 时，`async_job.job_status=COMPLETE`、`progress=100`。
- `FAILED` 仅用于系统异常、核心事实完全不可用或无法形成可验证结论。

### TravelPlanResponse 扩展

schema version 为 `1.16`，增加可空字段：

```json
{
  "planning_status": "NO_MATCH",
  "progress": 100,
  "plans": [],
  "recommendation_result": null,
  "constraint_analysis": {
    "result_type": "RELAXATION_AVAILABLE",
    "coverage": [],
    "alternatives": []
  },
  "async_job": {
    "job_status": "COMPLETE"
  }
}
```

约束：

- `planning_status=NO_MATCH` 时，正常 `plans` 必须为空，`recommendation_result` 必须为 null。
- `constraint_analysis` 在 `NO_MATCH` 时必须非空；其他状态允许为 null。
- 最近备选不得作为正常推荐方案消费，不得直接进入预订跳转。

### ConstraintAnalysis

```json
{
  "result_type": "RELAXATION_AVAILABLE",
  "summary": "没有找到18:00前到达的方案。当前已验证的铁路方案中，最早可于19:12到达。",
  "coverage": [
    {
      "transport_mode": "RAIL",
      "status": "VERIFIED",
      "message": "铁路班次已完成有效查询。"
    },
    {
      "transport_mode": "FLIGHT",
      "status": "UNAVAILABLE",
      "message": "航班数据源未启用，无法确认是否存在更早航班。"
    }
  ],
  "alternatives": []
}
```

字段：

- `result_type`：第一期固定为 `RELAXATION_AVAILABLE`；若无安全可展示备选，使用 `NO_SAFE_ALTERNATIVE`。
- `summary`：后端基于确定性模板生成的用户可见摘要，不由 LLM 生成。
- `coverage`：相关交通方式的查询覆盖。
- `alternatives`：经过安全门禁和 Pareto 筛选的备选，最多 3 条。

Coverage 状态：

- `VERIFIED`：Provider 有效查询完成，可用于范围内最优结论。
- `EMPTY`：有效查询完成但没有返回候选。
- `UNAVAILABLE`：Provider 未启用或当前路线未覆盖。
- `FAILED`：Provider 请求失败。
- `TIMEOUT`：Provider 查询超时。

只有相关交通方式全部为 `VERIFIED` 或 `EMPTY` 时，摘要才允许使用“所有交通方式中最早/最低”。存在 `UNAVAILABLE`、`FAILED` 或 `TIMEOUT` 时必须限定结论范围。

### RelaxationAlternative

```json
{
  "alternative_id": "alt_time_001",
  "category": "CLOSEST_TO_TIME",
  "plan": {},
  "violations": [],
  "preserved_constraints": [
    "MAX_TOTAL_COST",
    "TRANSPORT_MODE"
  ],
  "user_confirmation_required": true
}
```

- `category`：`CLOSEST_TO_TIME`、`CLOSEST_TO_BUDGET`、`LEAST_BEHAVIOR_CHANGE`。
- `plan`：完整 `TravelPlan` 快照，但必须满足：
  - `recommendation_eligibility=NOT_RECOMMENDED`
  - `can_be_selected_by_llm=false`
  - 不进入正常 `plans`
- `violations`：该备选违反的用户约束，至少 1 条。
- `preserved_constraints`：仍被满足的显式约束类型。
- `user_confirmation_required`：第一期固定为 true。

同一个计划可命中多个赛道；响应中按 `plan_id` 去重，并保留优先级最高的 category，避免重复展示。

### ConstraintViolation

```json
{
  "constraint_type": "LATEST_ARRIVAL",
  "relaxation_policy": "USER_CONFIRMATION_REQUIRED",
  "requested_value": {
    "datetime": "2026-07-13T18:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "source_timezone": "Asia/Shanghai"
  },
  "actual_value": {
    "datetime": "2026-07-13T19:12:00+08:00",
    "timezone": "Asia/Shanghai",
    "source_timezone": "Asia/Shanghai"
  },
  "deviation": {
    "kind": "DURATION",
    "value": 72,
    "unit": "MINUTE",
    "direction": "LATER"
  },
  "reason_code": "TIME_CONSTRAINT_TOO_LATE",
  "user_visible_message": "该方案预计19:12到达，比期望时间晚1小时12分钟。"
}
```

第一期 `constraint_type`：

- `LATEST_ARRIVAL`
- `EARLIEST_DEPARTURE`
- `ARRIVAL_TIME_WINDOW`
- `DEPARTURE_TIME_WINDOW`
- `MAX_TOTAL_COST`
- `ALLOWED_TRANSPORT_MODES`
- `EXCLUDED_TRANSPORT_MODES`
- `PREFERRED_RAIL_SEAT`
- `PREFERRED_FLIGHT_CABIN`

`deviation.kind` 与单位：

- 时间：`DURATION` + `MINUTE`。
- 金额：`MONEY` + `amount_minor/currency/scale` 结构，不使用 float。
- 交通方式：`MODE_SET` + `added_modes/removed_modes`。
- 席位/舱位：`CATEGORICAL` + 请求值/实际值。

不同 `kind` 不得由后端或前端换算成通用总分。

### 前端消费规则

- 轮询在 `planning_status=NO_MATCH` 且 `async_job.job_status=COMPLETE` 时结束。
- 显示独立“约束未满足”页面，不复用网络错误页或普通空态。
- 最多展示 3 个备选赛道，并显示具体偏差、覆盖范围和“不满足原始要求”。
- 用户点击备选只能先查看或确认放宽；确认后根据 violation 构造新的 `TravelRequest` 并重新调用 `POST /api/travel/plan/async`。
- 未确认前不得调用 `/api/redirect/booking`。
- 规划终态为 `NO_MATCH` 时上报 `PLANNING_NO_MATCH`，不得上报 `PLANNING_SUCCESS` 或系统失败事件。

### AppEventType 扩展

V1.16 为 `POST /api/events` 增加：

```txt
PLANNING_NO_MATCH
```

建议 metadata 只包含 `planning_status`、违反的 `constraint_type`、alternative 数量和 coverage 状态，不包含完整用户输入、详细地点或敏感乘客信息。

### 后端校验与生成规则

- 安全、合规、核心事实不完整或 `RiskLevel.BLOCKED` 的方案不得进入 `alternatives`。
- `alternatives` 必须来自 Provider 返回并经后端验证的候选，LLM 不得生成、修改或排序这些事实。
- 使用分类型计算器计算 deviation；跨类型不计算总分。
- 先执行 Pareto 支配筛选，再按赛道用确定性字典序选取，最终不超过 3 条。
- 摘要必须遵守 coverage 结论边界。
- 结构化日志记录原始候选数、正常候选数、备选数、reason_code 和 coverage；不得记录敏感信息。

### Empty 与 Loading 行为

- Loading：保持现有 `RUNNING/WAITING_SOURCE` 和轮询行为。
- `NO_MATCH + RELAXATION_AVAILABLE`：展示最近备选。
- `NO_MATCH + NO_SAFE_ALTERNATIVE`：展示无法满足的约束和修改条件入口，不展示方案卡。
- `FAILED`：展示系统/数据失败状态及可重试入口。

### 兼容与回滚

- V1.16 为前后端同步升级；`PlanningStatus` 新枚举会影响穷举判断，不能只部署后端。
- 功能开关关闭时沿用现有 `FAILED + missing_plan_explanations` 行为，不返回 `constraint_analysis`。
- 回滚不得改变现有 `COMPLETE/PARTIAL` 正常方案结构。

## 接驳地点解析与路线事实契约（V1.17，已实现）

适用于 `POST /api/travel/plan`、`POST /api/travel/plan/async`、`GET /api/travel/jobs/{job_id}` 和重试接口，Request、Query Params 与 HTTP Error Response 保持现有定义。

### 服务端生成规则

- 地点文本必须先通过本地已验证坐标、高德地理编码或高德 POI 搜索取得坐标，再调用地图路线 Provider。
- `LocalTransferOption` 的距离、耗时、费用和路径信息只能来自通过校验的 Provider 结果。
- 服务端不得为新响应生成 `route_status=RULE_ESTIMATED`；该枚举值在 V1.17 仅用于旧响应/旧客户端兼容。
- 某种接驳方式查询失败时，不得返回带虚构数字的可选项。
- 必需接驳段没有任何已验证方式时，该门到门计划不得进入正常 `plans` 或 AVAILABLE 推荐；失败通过 `SourceFailure` 和 `missing_plan_explanations` 表达。
- `MAP_COORDINATES_MISSING` 表示所有地点解析来源均未获得唯一完整坐标；不得在尚未调用高德搜索前返回该错误。
- 地点存在多个候选且无法按城市唯一消歧时，使用独立错误码 `MAP_LOCATION_AMBIGUOUS`，不得静默选择第一条。
- 高德地理编码/POI 搜索失败、超时、限流和空结果必须保留独立 Provider 失败信息。
- `walking_distance_meters` 在地图 Provider 未返回可验证步行距离时为 `null`，前端不得自行补默认值。
- 历史响应中的 `RULE_ESTIMATED/UNAVAILABLE` 仍可解析，但包含此类接驳事实的旧方案必须重新规划，不允许直接重算并生成新快照。

### Loading 与 Empty 行为

- 地点解析和路线查询属于异步规划阶段，前端继续显示 `RUNNING/WAITING_SOURCE`，不展示临时估算数字。
- 至少一种接驳方式验证成功时，只展示验证成功的方式。
- 没有完整门到门候选时，按现有 FAILED/NO_MATCH 业务规则返回可解释结果；不得展示只有干线事实、接驳数字为估算值的正常推荐卡。
- 前端遇到历史 `RULE_ESTIMATED` 可继续兼容展示，但新任务验收不得产生该状态。

## 交通方式覆盖与航班入口消费规则（V1.17，无字段变更，已实现）

适用于 `POST /api/travel/plan`、`POST /api/travel/plan/async`、`GET /api/travel/jobs/{job_id}` 和重试响应。首期复用 `plans`、`source_failures`、`blocked_plan_types`、`missing_plan_explanations` 与 `planning_status`，不增加 schema 字段。

### 服务端状态语义

- 本次查询范围由 `hard_constraints.allowed_transport_modes`、`hard_constraints.excluded_transport_modes` 和路线可适用性共同决定；显式排除的方式不得被报告为缺失。
- 默认城际请求在铁路站点和机场均可解析时，铁路与航班都属于查询范围。
- 任一查询范围内的交通方式存在完整门到门 `TravelPlan` 时，该方式可用。
- 某方式所有相关 Provider 都成功完成且均无 offer 时，才允许表达“未找到可验证方案”。
- 没有计划且存在限流、超时、挑战、配置或解析失败时，只能表达“暂不可确认”，不得表达“没有航班”。
- 查询范围内任一核心交通方式暂不可确认时，存在其他可用方案的响应使用 `planning_status=PARTIAL`；不得返回 `COMPLETE`。
- 每个 Provider 失败应使用对应 `source_id` 的独立 `SourceFailure`；`impacted_plan_types` 必须覆盖受影响的航班方案族。不得把多个来源的结果挂到最后尝试的 source_id。

建议稳定错误码：

```txt
FLIGHT_PROVIDER_EMPTY
FLIGHT_PROVIDER_RATE_LIMITED
FLIGHT_PROVIDER_TIMEOUT
FLIGHT_PROVIDER_CHALLENGE
FLIGHT_PROVIDER_INVALID_RESPONSE
FLIGHT_PROVIDER_DISABLED
```

其中 `FLIGHT_PROVIDER_EMPTY` 只能表示对应 Provider 请求成功并确认空结果，不能承载 429、超时或解析失败。

### 前端消费规则

- “综合推荐 / 更舒适 / 更省预算”是推荐目标；“铁路 / 航班”是交通方式入口，必须作为两个独立层级展示。
- 交通方式可用性从真实 `plans[*].segments[*].segment_type` 推导，不得由前端构造航班、票价、时刻或计划 ID。
- 航班无真实计划但属于查询范围时，航班入口保持可见并显示不可用状态；原因优先读取相关 `source_failures`，其次读取 `missing_plan_explanations`。
- 不可用入口可以打开原因说明、重试失败来源或 redirect-only 官方查询，但不得进入方案详情、重算或预订流程。
- 用户显式排除航班时，前端不显示“航班失败”警告；如产品保留航班入口，应标为“未纳入本次规划”，不能标为数据失败。
- 重试期间保留当前可用铁路结果并显示局部 loading；新响应返回后重新推导方式状态和候选，不沿用已失效的航班状态。

### Loading、Empty 与兼容

- 初次规划仍使用现有 `RUNNING/WAITING_SOURCE`；不提前展示伪造的航班骨架数值。
- 旧 V1.17 响应若只有聚合 `SourceFailure`，前端使用保守“航班暂不可确认”，不得反推为“无航班”。
- 本规则不改变外部 schema，也不需要数据库迁移；前后端仍需同步发布，以避免后端返回 `PARTIAL` 而旧前端继续隐藏交通方式缺口。

## FlyAI 唯一票务事实源契约（V1.18，代码已实现 / 在线验收阻塞）

- `DataSourceType` 新增 `OTA`；FlyAI 航班和铁路事实统一使用 `source_id=fliggy_flyai`、`source_type=OTA`。
- `BookingRedirect.redirect_type` 与 `BookingRedirectRequest.redirect_type` 新增 `FLIGGY`；历史 `AIRLINE`、`RAIL_12306` 记录仍可解析，但新计划不再生成这两类票务跳转。
- 航班 item 必须包含精确 `ticketPrice`（或官方兼容字段 `adultPrice`）、至少一段完整航段、响应实际返回的舱位和 allowlisted HTTPS `jumpUrl`。
- 铁路 item 必须包含精确 `price`、实际车次/车站/时刻、响应实际返回的席别和 allowlisted HTTPS `jumpUrl`；`3xx`、`5xx`、区间或空价格以 `FLIGGY_PRICE_NOT_EXACT` 拒绝，不进入计划。
- CLI 非零退出、非空 stderr、超时、非完整 JSON、业务状态失败、体验模式提示或结构漂移全部 fail-closed；错误不触发航司、浏览器 worker 或 12306 fallback。
- 相同规范化查询使用 60 秒短缓存和 single-flight；日志仅允许 source/命令类型、耗时、退出分类、item 数和响应哈希，不记录 Key、完整 URL 或 stdout。
- 正式 Key、目标 Windows 环境 exit 0 与 50 样例 cold/warm P50/P95/P99 门禁尚未完成，因此 `.env.example` 保持 `TRAVEL_SOURCE_FLIGGY_FLYAI_ENABLED=false`。
