# AI 出行规划应用数据源准入规范 V1.1

版本：V1.1  
日期：2026-05-26  
对齐 Schema：AI_Travel_Planner_Data_Schema_V1.15.md

---

## Changelog

| 日期 | 版本 | 更改点 |
|---|---|---|
| 2026-05-26 | V1 | 创建数据源准入规范初版，定义数据源分级、白名单机制、环境使用规则、生产准入条件、禁止数据源、fallback、缓存、商务 Review Checklist、接入台账和 Codex 实现约束。 |
| 2026-05-26 | V1.1 | 对齐 `AI_Travel_Planner_Data_Schema_V1.15`：统一 DataSourceConfig、DataSourceMetadata、SourceFailure、DataSourceRuntimeStatus、DataSourceStatusResponse、ErrorResponse、BookingRedirectRequest / Response 的字段和语义；明确 `/api/data-sources/status` 返回运行状态而非配置对象；补齐 request_id / trace_id / correlation_id / idempotency_key 透传规则；统一 failure_class、message、fallback_used、source_used_id、fallback_reason 等字段命名。 |

---

## 1. 对齐原则

本文档必须与 `AI_Travel_Planner_Data_Schema_V1.15.md` 保持一致。

Schema V1.15 是所有 JSON Schema 的唯一维护源。本文档只定义数据源准入、治理、Review 和实现规则，不重复定义新的 Schema 字段。

如果本文档与 Schema V1.15 冲突，以 Schema V1.15 为准。

---

## 2. V1.15 对齐范围

本次 V1.1 与以下 Schema 对齐：

1. `DataSourceMetadata`
2. `DataSourceConfig`
3. `SourceFailure`
4. `DataSourceRuntimeStatus`
5. `DataSourceStatusResponse`
6. `ErrorResponse`
7. `BookingRedirectRequest`
8. `BookingRedirectResponse`
9. `TravelPlanResponse`
10. `MissingPlanExplanation`
11. `DataQuality`
12. `TimePoint`
13. `Money`
14. `MoneyDelta`

---

## 3. 数据源角色边界

### 3.1 DataSourceConfig：配置契约

`DataSourceConfig` 是生产、测试、开发环境的数据源白名单配置契约。

它用于回答：

1. 这个数据源是否允许被系统使用？
2. 这个数据源在哪个环境启用？
3. 是否已授权？
4. 是否允许商用？
5. QPS 和 SLA 是什么？
6. fallback 数据源是什么？
7. 是否 enabled？

`DataSourceConfig` 不应直接作为 `/api/data-sources/status` 的响应对象。

---

### 3.2 DataSourceRuntimeStatus：运行状态契约

`DataSourceRuntimeStatus` 用于 `/api/data-sources/status`。

它用于回答：

1. 当前数据源健康状态如何？
2. 是否 enabled？
3. 最近一次成功时间是什么？
4. 最近一次失败时间是什么？
5. 最新 failure 是什么？
6. 平均延迟是多少？
7. 是否 degraded？
8. degraded reason 是什么？

状态接口不得返回第三方密钥、内部 token、账号、未脱敏错误堆栈或敏感配置。

---

### 3.3 DataSourceMetadata：事实数据来源

所有用户可见事实数据必须携带 `DataSourceMetadata`。

包括：

1. 车站候选。
2. 机场候选。
3. 高铁分段。
4. 航班分段。
5. 本地接驳分段。
6. 座席选项。
7. 舱位选项。
8. 费用明细。
9. 风险数据。
10. 跳转数据。
11. 内部计算结果。

内部计算结果也必须使用 `source_type = INTERNAL_CALCULATION`。

---

### 3.4 SourceFailure：失败事件契约

数据源失败必须生成 `SourceFailure`。

V1.15 要求 `SourceFailure` 保留以下链路追踪字段：

1. `request_id`
2. `trace_id`
3. `correlation_id`
4. `source_id`
5. `source_used_id`
6. `fallback_source_id`
7. `fallback_reason`
8. `fallback_used`
9. `final_handling_strategy`
10. `impacted_plan_types`
11. `occurred_at`

字段命名以 Schema 为准：

| 旧/架构描述 | V1.15 Schema 字段 |
|---|---|
| `failure_type` | `failure_class` |
| `error_message` | `message` |
| `final_strategy` | `final_handling_strategy` |
| `source_final_used` | `source_used_id` |

---

## 4. 数据源分级

### 4.1 S 级

官方或准官方入口。

示例：

1. 12306 官方购票入口。
2. 航司官网官方入口。
3. 官方地图开放平台。
4. 官方公开 API。

使用规则：

1. 可用于跳转和最终确认。
2. 后台调用必须有明确授权。
3. 不得逆向。
4. 不得绕过验证码。
5. 不得绕过登录态。
6. 不得自动下单。
7. 不得自动支付。

---

### 4.2 A 级

大型平台、商业 API、可签约数据服务。

示例：

1. 高德地图开放平台。
2. 百度地图开放平台。
3. OAG。
4. 飞常准商业 API。
5. 航旅纵横商业合作 API。
6. OTA / NDC / 授权票务数据服务。

生产准入前必须满足：

1. 公司主体清晰。
2. 可签合同。
3. 可商用。
4. 可展示数据。
5. 可用于推荐。
6. 有 SLA。
7. 有 QPS。
8. 有错误码。
9. 有 fallback 或降级策略。
10. 可审计。

---

### 4.3 B 级

开发验证、测试环境或辅助数据源。

允许：

1. DEV 环境使用。
2. TEST 环境使用。
3. 用于 mock。
4. 用于 sandbox。
5. 用于非生产验证。

限制：

1. 默认不得进入 PROD。
2. 进入 PROD 必须通过商务 Review。
3. 进入 PROD 必须升格为 A 级或 S 级。

---

### 4.4 C 级

禁止使用。

包括：

1. GitHub 逆向接口。
2. 个人维护票务接口。
3. 无公司主体接口。
4. 无商用授权接口。
5. 论坛 / 博客接口。
6. 需要绕过验证码的接口。
7. 需要绕过登录态的接口。
8. 需要伪造客户端的接口。
9. 自动抢票接口。
10. 自动下单接口。
11. 自动支付接口。
12. 无数据来源说明的余票接口。

---

## 5. 生产环境准入规则

生产环境启用数据源必须满足：

```text
environment == PROD
enabled == true
license_status == APPROVED
commercial_allowed == true
authority_level != C
```

并且必须具备：

1. `source_id`
2. `source_name`
3. `source_type`
4. `authority_level`
5. `license_status`
6. `commercial_allowed`
7. `update_frequency`
8. `sla_level`
9. `qps_limit`
10. `fallback_source_id`
11. `enabled`
12. `environment`

以上字段必须符合 Schema V1.15 的 `DataSourceConfig`。

---

## 6. 环境规则

### 6.1 DEV

允许：

1. mock 数据源。
2. 静态样例数据。
3. sandbox API。
4. 本地假数据。

禁止：

1. C 级数据源。
2. 逆向接口。
3. 绕过验证码。
4. 绕过登录态。
5. 自动下单。
6. 自动支付。

---

### 6.2 TEST

允许：

1. sandbox API。
2. trial API。
3. `license_status = PENDING_REVIEW` 的测试数据源。
4. 已脱敏生产样例数据。

限制：

1. 不得面向真实用户。
2. 不得展示为真实可购票结果。
3. 必须标明数据源状态。
4. 必须记录 `source_id`。

---

### 6.3 PROD

只允许：

1. `environment = PROD`
2. `enabled = true`
3. `license_status = APPROVED`
4. `commercial_allowed = true`
5. `authority_level != C`
6. 已完成商务 Review
7. 已完成项目 Owner 批准

---

## 7. 数据源类型准入要求

### 7.1 地图数据源

用途：

1. 地址解析。
2. POI 搜索。
3. 坐标解析。
4. 驾车路线。
5. 公交 / 地铁路线。
6. 路况。
7. 地图跳转。

准入要求：

1. 必须来自官方开放平台或授权服务商。
2. 必须允许商用。
3. 必须允许展示路线结果。
4. 必须明确坐标系。
5. 必须明确 QPS。
6. 必须明确缓存策略。
7. 必须支持错误码。
8. 必须有 fallback 或降级策略。

---

### 7.2 高铁 / 铁路数据源

用途：

1. 车站查询。
2. 站站车次。
3. 经停站。
4. 票价。
5. 余票。
6. 座席。
7. 中转。
8. 票源增强覆盖校验。
9. 12306 跳转。

准入要求：

1. 数据来源清晰。
2. 允许商用。
3. 允许展示车次、票价、余票。
4. 允许系统基于数据做推荐。
5. 支持经停站或站序。
6. 支持座席价格。
7. 明确余票实时性。
8. 明确 QPS。
9. 明确 SLA。
10. 明确缓存限制。

禁止：

1. 12306 逆向。
2. 个人 API。
3. 自动登录。
4. 自动抢票。
5. 自动下单。
6. 自动支付。
7. 绕过风控。

---

### 7.3 航班数据源

用途：

1. 航班计划。
2. 航班动态。
3. 延误。
4. 取消。
5. 前序航班。
6. 机型。
7. 航站楼。
8. 最小中转时间。
9. 航班中转。
10. 舱位价格。

准入要求：

1. 有商业 API 或授权合作。
2. 明确覆盖范围。
3. 明确刷新频率。
4. 明确是否支持前序航班。
5. 明确是否支持舱位价格。
6. 明确是否支持中转计算。
7. 明确是否支持最小中转时间。
8. 有 SLA。
9. 有 QPS。
10. 有 fallback 或降级策略。

航班数据建议拆分：

| 数据类型 | 示例 |
|---|---|
| 航班动态 | 起飞、到达、延误、取消、前序航班 |
| 机票价格 | 舱位、价格、库存、税费、退改规则 |

---

### 7.4 OTA / 票价 / 余票数据源

用途：

1. 高铁票价。
2. 高铁余票。
3. 机票价格。
4. 舱位库存。
5. 跳转购票。
6. 分销合作，后续扩展。

准入要求：

1. 可签合同。
2. 可商用。
3. 允许展示价格。
4. 允许展示库存。
5. 允许 AI 推荐。
6. 允许跳转。
7. 明确缓存策略。
8. 明确退改签责任边界。
9. 明确售后责任边界。

第一阶段原则：

```text
只做规划、推荐、解释和跳转，不做无授权交易闭环。
```

---

### 7.5 打车 / 接驳数据源

用途：

1. 打车费用估算。
2. 接驳耗时。
3. 距离。
4. 实时路况。
5. 导航跳转。
6. 打车平台跳转。

准入要求：

1. 允许展示路线估算。
2. 费用必须标记为 estimated。
3. 实际价格以平台为准。
4. 明确缓存限制。
5. 支持跳转。
6. 输出必须对齐 `LocalTransferSegment`。

---

### 7.6 LLM 服务

LLM 属于 `source_type = LLM`。

准入要求：

1. 支持结构化输出。
2. 支持 JSON Schema 校验或等效结构化输出约束。
3. 支持 model_name 记录。
4. 支持 prompt_version 记录。
5. 支持超时控制。
6. 支持 fallback 或确定性降级。
7. 不作为事实数据源。

LLM 禁止：

1. 生成车次。
2. 生成航班号。
3. 生成价格。
4. 生成余票。
5. 修改候选方案事实字段。
6. 选择 `can_be_selected_by_llm = false` 的方案。
7. 选择 `recommendation_eligibility = BLOCKED` 的方案。

---

## 8. 数据源失败处理

数据源失败必须按 A/B/C/D 分级处理。

### 8.1 A 类：辅助数据失败

示例：

1. 前序航班缺失。
2. 天气缺失。
3. 实时路况缺失。
4. 准点率缺失。

处理：

1. 可返回方案。
2. 降低 DataQuality。
3. 降低 ComfortScore confidence。
4. 写入 `SourceFailure`。
5. 前端展示 user_visible_message。

---

### 8.2 B 类：有 fallback 的失败

示例：

1. 高德失败切百度。
2. 主航班源失败切备用源。
3. 主地图源失败切备用源。

处理：

1. Retry。
2. Fallback。
3. `fallback_used = true`
4. `fallback_source_id != null`
5. `source_used_id != null`
6. `fallback_reason != null`
7. 写入 `SourceFailure`

---

### 8.3 C 类：核心事实数据失败

示例：

1. 高铁车次无法获取。
2. 高铁票价无法获取。
3. 航班时刻无法获取。
4. 航班价格无法获取。
5. 地图路线无法获取。

处理：

1. 不生成对应方案。
2. 返回其他可用方案。
3. 生成 `MissingPlanExplanation`。
4. 写入 `source_failures[]`。
5. 不允许 LLM 补全。

---

### 8.4 D 类：安全关键数据失败

示例：

1. 中转时间无法计算。
2. 站序无法确认。
3. 票面区间覆盖无法确认。
4. 最小航班中转时间无法确认。
5. 是否需要补票无法判断。

处理：

1. 阻断相关方案。
2. 加入 `blocked_plan_types[]`。
3. TravelPlan 设置：
   - `recommendation_eligibility = BLOCKED`
   - `can_be_selected_by_llm = false`
4. 不进入 LLM 推荐候选池。
5. 不进入三张主推荐卡。

---

## 9. TravelPlanResponse 与失败解释

所有规划响应必须能解释：

1. 哪些数据源失败。
2. 哪些组件缺失。
3. 哪些方案类型被阻断。
4. 为什么没有生成某类方案。
5. 当前结果是否为 partial。
6. 是否存在 async_job。

因此 `TravelPlanResponse` 必须包含：

1. `source_failures[]`
2. `missing_components[]`
3. `blocked_plan_types[]`
4. `missing_plan_explanations[]`
5. `user_visible_warnings[]`

---

## 10. `/api/data-sources/status` 规则

`GET /api/data-sources/status` 必须返回 `DataSourceStatusResponse`。

它返回 `DataSourceRuntimeStatus[]`，不得直接返回 `DataSourceConfig[]`。

原因：

1. `DataSourceConfig` 是内部配置契约。
2. Runtime status 是对外健康状态契约。
3. 配置中可能包含敏感治理信息。
4. 状态接口只应暴露运行健康度和已脱敏失败原因。

---

## 11. `/api/health` 规则

`GET /api/health` 必须返回 `HealthResponse`。

要求：

1. 必须包含 `schema_version`。
2. 必须包含 `status`。
3. 必须包含 `service_name`。
4. 必须包含 `version`。
5. 必须包含 `checked_at`。

---

## 12. API 错误响应规则

所有 4xx / 5xx 必须复用 `ErrorResponse`。

适用接口：

1. `POST /api/travel/parse`
2. `POST /api/travel/plan`
3. `POST /api/travel/recalculate`
4. `GET /api/travel/plans/{plan_id}`
5. `GET /api/data-sources/status`
6. `POST /api/redirect/booking`
7. `GET /api/health`

不得返回临时结构：

```json
{ "error": "xxx" }
```

或：

```json
{ "message": "xxx" }
```

必须包含：

1. `schema_version`
2. `request_id`
3. `error_code`
4. `message`
5. `user_visible_message`
6. `retryable`
7. `details`
8. `generated_at`

---

## 13. 跳转数据源规则

### 13.1 BookingRedirectRequest

跳转请求只用于生成外部跳转，不得携带：

1. 第三方账号。
2. 第三方密码。
3. 支付信息。
4. 自动下单参数。
5. 抢票参数。
6. 实名乘车人敏感信息。

### 13.2 BookingRedirectResponse

跳转响应必须：

1. 包含 `generated_at`。
2. 标记 `url_available`。
3. 若无可用 URL，提供 `fallback_instruction`。
4. 不承诺最终票价或库存。
5. 不执行交易闭环。

---

## 14. 缓存规则

### 14.1 可缓存数据

| 数据类型 | 建议 |
|---|---|
| 地点解析 | 可缓存 |
| 车站候选 | 可缓存 |
| 机场候选 | 可缓存 |
| 地图路线 | 短 TTL |
| 高铁时刻 | 中 TTL |
| 航班计划 | 中 TTL |
| LLM 推荐结果 | 与 candidate_plan hash 绑定 |

### 14.2 谨慎缓存数据

| 数据类型 | 规则 |
|---|---|
| 高铁余票 | 极短 TTL 或不缓存 |
| 机票库存 | 极短 TTL 或不缓存 |
| 舱位价格 | 极短 TTL 或不缓存 |
| 票源增强覆盖校验 | 不使用过期缓存进入主推荐 |
| 最小中转时间 | 不使用过期缓存进入主推荐 |

### 14.3 stale-while-revalidate

允许对低风险数据使用 stale-while-revalidate。

不得对以下数据使用过期缓存进入主推荐：

1. 高铁余票。
2. 机票库存。
3. 票源增强覆盖校验。
4. 最小中转时间。
5. 安全关键数据。

---

## 15. 商务 Review Checklist

### 15.1 基础信息

| 项目 | 内容 |
|---|---|
| 公司名称 |  |
| 官网 |  |
| 联系人 |  |
| 合作方式 | API / SDK / 跳转 / 分销 |
| 数据类型 | MAP / RAIL / FLIGHT / OTA / TAXI |
| 覆盖范围 |  |
| 是否有 sandbox |  |

### 15.2 授权与合规

| 问题 | 结果 |
|---|---|
| 是否允许商用 |  |
| 是否允许展示数据 |  |
| 是否允许 AI 推荐 |  |
| 是否允许缓存 |  |
| 是否允许跳转 |  |
| 是否允许价格展示 |  |
| 是否允许余票/库存展示 |  |
| 是否有合同 |  |
| 是否有数据来源说明 |  |

### 15.3 技术能力

| 问题 | 结果 |
|---|---|
| 是否有 API 文档 |  |
| 是否有 QPS |  |
| 是否有 SLA |  |
| 是否有错误码 |  |
| 是否支持 fallback |  |
| 是否支持 sandbox |  |
| 是否支持数据更新时间 |  |

### 15.4 费用

| 项目 | 内容 |
|---|---|
| 计费方式 | 按调用 / 按月 / 分成 |
| 免费额度 |  |
| 超额价格 |  |
| 最低消费 |  |
| 合同周期 |  |
| 佣金模式 |  |

---

## 16. 数据源接入台账模板

| source_id | source_name | source_type | authority_level | environment | license_status | commercial_allowed | enabled | qps_limit | sla_level | fallback_source_id | owner | status | next_action |
|---|---|---|---|---|---|---|---|---:|---|---|---|---|---|
| amap | 高德地图 | MAP | A | PROD | APPROVED | true | true | 50 | STANDARD | baidu_map | Owner | READY | 监控 |
| baidu_map | 百度地图 | MAP | A | PROD | APPROVED | true | true | 50 | STANDARD | null | Owner | READY | fallback |
| rail_provider_001 | 待定铁路数据源 | RAIL | B | TEST | PENDING_REVIEW | false | false | 0 | TBD | null | Owner | REVIEW | 商务确认 |
| flight_provider_001 | 待定航班数据源 | FLIGHT | B | TEST | PENDING_REVIEW | false | false | 0 | TBD | null | Owner | REVIEW | 商务确认 |

---

## 17. Codex 实现要求

Codex 必须实现：

1. 读取 `DataSourceConfig`。
2. 环境隔离。
3. 生产环境白名单校验。
4. 所有事实数据注入 `DataSourceMetadata`。
5. 数据源失败生成 `SourceFailure`。
6. fallback 记录。
7. cache metadata 记录。
8. data quality 影响范围记录。
9. missing plan explanation 生成。
10. blocked plan types 生成。
11. `/api/data-sources/status` 返回 `DataSourceRuntimeStatus`。
12. 所有 API 错误返回 `ErrorResponse`。
13. request_id / trace_id / correlation_id / idempotency_key 透传。

Codex 不得：

1. 自行接入未知数据源。
2. 硬编码第三方接口。
3. 使用逆向接口。
4. 使用无授权接口。
5. 在数据源失败时让 LLM 补全事实。
6. 跳过 DataSourceConfig 校验。
7. 在 PROD 启用 `PENDING_REVIEW` 数据源。
8. 在 PROD 启用 mock 数据。
9. 直接把 `DataSourceConfig` 暴露给前端状态接口。
10. 返回临时错误结构。

---

## 18. 验收标准

### 18.1 配置验收

1. 所有数据源均有 `DataSourceConfig`。
2. PROD 只启用 APPROVED 数据源。
3. C 级数据源无法启用。
4. mock 无法进入 PROD。
5. qps_limit、sla_level、fallback_source_id 均有定义。

### 18.2 调用验收

1. 所有 Adapter 调用携带 source_id。
2. 所有事实字段携带 DataSourceMetadata。
3. fallback 触发时生成 SourceFailure。
4. SourceFailure 携带 request_id / trace_id / correlation_id。
5. 安全关键数据失败时阻断推荐。

### 18.3 API 验收

1. `/api/data-sources/status` 返回 DataSourceRuntimeStatus。
2. `/api/health` 返回 HealthResponse。
3. 所有 4xx / 5xx 返回 ErrorResponse。
4. 所有业务响应透传 request_id / trace_id / correlation_id / idempotency_key。
5. BookingRedirectResponse 包含 generated_at。

### 18.4 前端验收

1. 能展示数据来源。
2. 能展示更新时间。
3. 能展示数据缺失原因。
4. 能展示为什么没有某类方案。
5. 能展示方案被阻断原因。
6. 能展示价格和余票以最终平台为准。

### 18.5 LLM 验收

1. LLM 不调用数据源。
2. LLM 不生成事实数据。
3. LLM 只引用候选 plan_id。
4. 数据源失败时 LLM 不得补齐缺失车次、航班、价格、余票。
5. LLM 不得选择 `can_be_selected_by_llm = false` 的方案。

---

## 19. 后续待细化

1. 每个候选数据源正式 Review 表。
2. 商务邮件模板。
3. 数据源 API 字段映射。
4. 数据源成本估算。
5. 数据源 SLA 监控规则。
6. 数据源切换策略。
7. 数据源治理后台。
