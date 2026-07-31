# ARC-20260801-02 约束感知候选与可解释备选开发任务

来源：`job_7519c4c26c98` 假性 `NO_MATCH` 架构核查。

状态：已完成。完成时间：2026-08-01 07:53:36 +08:00。代码提交：`b235622`、`9a4008f`、`a37d381`、`524922e`。

## 1. 已确认根因

- 12306 首个站点对返回 92 条，Planner 在约束评估前只构建按发车时间排序的前 4 条，导致中午后的真实车次全部未评估。
- D3145 只是错误截断集合中偏差最小的一条，不是全量结果中唯一或全局最近备选。
- 时间约束使用干线段时刻，忽略已生成的门到门 `plan.departure_time/arrival_time`。
- 海航返回 5 个两段中转 itinerary，解析器因“Segment 数必须等于 1”全部拒绝；当前请求和 Planner 均允许中转。
- NO_MATCH 详情仅展示完整度和风险等级，无法支持放宽决策。

## 2. 后端任务

### 2.1 Offer 预选

- 新增纯函数预选模块，输入 Provider offers、`TravelRequest` 和构建预算，输出 `LIKELY_FEASIBLE`、`NEEDS_FULL_PLAN`、`RELAXATION_RESERVE`、`REJECTED_UNSAFE`。
- 预选只使用 Provider 事实，不调用地图、不伪造接驳时间或总价。
- 删除直接铁路路径的 `result.offers[:max_plans]` 先截断行为。
- 对全部已验证 offer 元数据做约束分桶和稳定排序；按站点、时间和偏好保持必要多样性。
- `max_plans` 限制成功构建的完整计划数。某 offer 因接驳、地点或最终约束失败时，继续尝试后续 offer。
- 正常候选与 relaxation reserve 使用独立预算；正常候选为空时才让 reserve 进入备选分析。
- 日志增加原始 offer 数、各分桶数、尝试构建数、构建成功数、最终合格数和最近备选数。

### 2.2 门到门时间语义

- `evaluate_time_constraints()` 优先使用 `TravelPlan.departure_time/arrival_time`，不得主动用首末干线段覆盖。
- 计划缺少完整门到门时间时 fail-closed 或产生明确缺口；不得静默降级为干线时刻。
- 对 earliest/latest 和 time window 去重处罚，保留现有时区比较。
- 日志同时记录干线时刻与门到门时刻，便于核查。

### 2.3 海航两段 itinerary

- 将海航 Flight block 解析为有序 1..2 段；超过 2 段返回明确不支持 error code。
- 每段校验航班号、实际机场、日期和时刻；校验相邻机场、时间顺序、最小换乘以及跨机场规则。
- 只有票价/舱位能证明覆盖完整 itinerary 时才构造 offer。
- 输出完整 `FlightOffer.segments`，复用既有多航段 Planner 构建 `TRANSFER_FLIGHT`。
- 区分有效空结果与 `UNSUPPORTED_RESPONSE/PARSER_REJECTED_ALL`；外部 schema 不变时用明确 error code 和用户文案映射。
- coverage 聚合：全部来源有效空才为 `EMPTY`；空与失败混合时为 `FAILED`，并保留逐来源说明；有可验证 offer 时为 `VERIFIED`。

## 3. 前端任务

- 扩展 `ConstraintNoMatchScreen` 的只读备选详情，展示：
  - 门到门出发/到达、总耗时与总费用；
  - 首末接驳和所有铁路/航班段；
  - 车次/航班、席别/舱位；
  - 每个 violation 的请求值、实际值和偏差；
  - preserved constraints；
  - 数据来源、更新时间以及有具体解释的风险/缺口。
- 明确展示“确认后将放宽的条件”，展开详情不修改状态。
- 使用只读 presentation 复用正常结果组件/helper，不得渲染购票入口。
- 在 NO_MATCH 页从 `source_failures` 派生逐航司查询说明，区分有效空、解析/结构不支持、超时、限流。
- 现有 `constraint_analysis.coverage` 仍作为交通方式摘要，不把“部分来源失败”写成“市场无班次”。

## 4. 目标文件

- `backend/app/services/planner.py`
- `backend/app/services/offer_preselection.py`（建议新增）
- `backend/app/services/constraints/time_calculator.py`
- `backend/app/services/constraints/relaxation_selector.py`
- `backend/app/data_sources/flight_providers.py`
- `frontend/src/components/constraints/ConstraintNoMatchScreen.tsx`
- 可复用的 `frontend/src/components/results/*` presentation helper
- 对应后端和前端测试文件

外部 API schema 保持 `1.17`，不做数据库迁移。

## 5. 实现顺序

1. 先补固定失败 fixture 和红灯测试。
2. 修正门到门时间约束。
3. 实现 offer 预选并移除先截断。
4. 实现海航两段解析与 outcome 聚合。
5. 完成备选详情和航班逐来源说明。
6. 运行全量回归、schema diff 和低频真实 smoke。

## 6. 验收门禁

- 92 条铁路 fixture 中前四条早于 12:00、后续存在可行车次时不得返回 `NO_MATCH`。
- 只允许门到门 12:00 后出发的计划满足“12 点从地址出发”。
- D3145 不再因前四条截断成为唯一备选。
- 海航 fixture 至少解析 HU7606 + HU6377 为一个两段 itinerary；价格、机场、时刻和换乘均通过一致性校验。
- 三个航司的逐来源状态准确可见。
- 备选详情包含路线、时间、费用、偏差和确认影响，不包含 booking action。
- 地图调用保持有界；schema export 无 diff；无模拟事实。

## 7. 回滚

- 约束感知预选、海航多段解析和增强详情分别使用独立开关。
- 回滚预选实现时不得恢复先取前 N 条再评估；可临时使用全量事实过滤加小规模完整构建。
- 回滚海航多段解析时保留明确“不支持中转结构”状态，不得改报空结果。

## 8. 完成记录

- 新增纯函数铁路 offer 预选，对完整 Provider 元数据分为 `LIKELY_FEASIBLE`、`NEEDS_FULL_PLAN`、`RELAXATION_RESERVE`、`REJECTED_UNSAFE`；删除直接铁路先取前 N 条的行为。
- 正常候选与备选使用独立构建预算，完整计划约束失败后继续扫描后续 offer；92 条 fixture 验证前四条过早时仍能得到满足门到门出发约束的方案。
- 时间约束统一使用 `TravelPlan.departure_time/arrival_time`；缺少所需门到门时间时 fail-closed，并记录干线与门到门时间日志。
- 海航解析器支持严格校验的 1–2 段 itinerary；`HU7606 + HU6377` fixture 验证完整机场、时刻、45 分钟换乘和行程级总价。
- NO_MATCH 详情增加门到门时间、费用、所有分段、席别/舱位、请求/实际/偏差、保留约束、数据源、更新时间、风险与缺口；不渲染购票入口。
- NO_MATCH 页按 `source_failures` 展示逐航司有效空、结构不支持、超时、限流、禁用或失败说明。
- 三处能力分别由 `TRAVEL_CONSTRAINT_AWARE_PRESELECTION_ENABLED`、`TRAVEL_HAINAN_MULTISEGMENT_ENABLED`、`EXPO_PUBLIC_ENHANCED_NO_MATCH_DETAIL_ENABLED` 控制；关闭预选优化也不会恢复 first-N 截断。
- 外部 API schema 保持 1.17，无数据库迁移；schema export 无差异。
- 验证：后端 250 passed；前端 26 passed；TypeScript、Python compileall、Web/iOS/Android Expo 导出、schema diff 与 `git diff --check` 通过。Ruff 未安装，未执行。
