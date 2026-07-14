# ARC-20260714-01 修复铁路中转候选提前截断与同站接驳误建模

来源：用户反馈与架构诊断，2026-07-14。

完成状态：已完成。完成时间：2026-07-14 12:05:53 +08:00。代码提交：`bdff0d67300a04676da2ba3ac45131575850d4fb`。

详细设计见 `docs/ARCHITECTURE.md`“铁路中转完整候选匹配架构（V1.17，已实现）”。

实现摘要：新增独立完整候选匹配器与安全策略配置，使用 station code 判断同站、二分定位可连接第二程、跨站真实地图接驳、全局验证后排序和独立 `RAIL_CONNECTION_NOT_FOUND` 语义；API schema、数据库和前端类型保持不变。

## 背景与证据

- 当前 `planner.py` 在连接校验前使用 `first_result.offers[:2]` 和 `second_result.offers[:2]`，最多检查 4 种组合。
- 岳阳至张家口的真实查询中，G502 于 14:12 到达北京西，D6649 于 14:58 发车，46 分钟满足 45 分钟换乘下限，但 D6649 不在第二程最早两个 offer 中，因此未被检查。
- 北京西完整 offer 集存在可行连接，本次 `TRANSFER_RAIL` 为空属于算法假阴性。
- 两段铁路之间当前无条件构造 taxi 接驳；同一北京西站不应依赖地图路线。
- Provider 失败与连接匹配失败目前混用错误语义，容易把局部缺票价错误表述为整个中转规划不可用。

## 开发目标

- 对 Provider 返回的完整铁路事实执行确定性连接匹配，验证后再限制候选数量。
- 正确识别同站与跨站换乘，避免同站零距离地图查询阻断方案。
- 不增加 12306 请求次数，不放宽 45 分钟安全门槛，不生成任何模拟车次、票价或接驳事实。
- 第一阶段保持 API schema V1.17、数据库和前端类型不变。

## 开发任务 A：连接匹配器

1. 新增 `backend/app/services/rail_connection_matcher.py`，不得继续扩大 `planner.py`。
2. 定义仅供后端内部使用的 `RailConnectionPolicy` 与 `RailConnectionCandidate`；不要加入公共 API Schema。
3. Policy 至少包含：
   - 同站最低换乘时间，默认 45 分钟。
   - 最大等待时间，默认 360 分钟。
   - 每个第一程和每个中转站的验证后候选上限。
   - `allow_overnight_transfer=false`。
4. 第一、二程 offer 按到发时间和稳定事实键去重、排序。
5. 为第二程发车时间建立索引；对每个第一程使用二分查找定位第一班满足最低换乘时间的第二程。
6. 从定位点扫描至最大等待边界，校验时间、车站身份、票价、席别、重复车次和 Provider 元数据。
7. 候选稳定键至少包含第一/二程车次、规范化车站和到发时间，避免别名查询产生重复方案。
8. 禁止以扩大 `[:2]`、`[:10]` 或固定笛卡尔积窗口代替完整连接匹配。

## 开发任务 B：规划器接入

1. `_build_dynamic_transfer_rail_plans()` 保留 Provider 查询和问题聚合职责，连接组合交给新 matcher。
2. Provider 完整 offer 必须先进入 matcher；`max_plans` 只能应用于验证和排序后的计划候选。
3. 对每个中转站先形成内部连接候选，再进行全局排序，避免第一个中转站占满 `max_plans`。
4. 排序采用确定性字典序：不可放宽安全门禁、用户硬约束、到达时间/总耗时、等待时间、费用、风险、稳定键。
5. 推荐候选仍必须经过现有 `candidate_generator` 和 Recommendation 边界，matcher 不负责 LLM 推荐。
6. 北京西回归数据必须能够选中 G502 + D6649 或同等满足门槛的真实组合。

## 开发任务 C：同站与跨站换乘

1. 使用规范化 `station_id/station_code` 判断同站，不只比较展示名称。
2. 同站换乘：
   - 不调用 `taxi()`、地理编码或地图路线 Provider。
   - 不生成虚构的 20 分钟/0 费用接驳段。
   - 以两段真实到发时间计算等待和总行程时间。
3. 跨站换乘：
   - 必须通过现有地点解析与地图 Provider 得到真实路线。
   - 最低所需时间为出站缓冲、真实地面接驳时间、进站缓冲之和。
   - 路线失败、歧义或时间不足时淘汰该连接并记录准确原因。
4. 无法确认是否同站时不得猜测，按跨站验证路径处理。
5. 第一阶段不新增 `RailConnectionSegment`；若后续需要前端显式展示站内等待，另开 schema/API 任务。

## 开发任务 D：错误语义与可观测性

1. Provider 空结果、缺票价、超时、限流继续使用现有 Provider 级错误码。
2. 两段 Provider 均有有效事实但没有安全连接时，使用 `RAIL_CONNECTION_NOT_FOUND`，不得写成 `RAIL_PROVIDER_MISSING_PRICE`。
3. 不得因汉口一条缺票价记录覆盖北京西、西安北等其他中转站的查询结论。
4. 每个 `origin + hub + destination + date` 记录：
   - `first_offer_count`、`second_offer_count`。
   - `pairs_examined`。
   - 发车过早、换乘缓冲不足、等待过长、跨站路线失败的淘汰数。
   - `valid_connection_count`、`selected_connection_count`。
5. 最终任务日志能够区分 Provider 事实缺失、连接无匹配、接驳失败和用户约束淘汰。
6. 日志不得包含完整用户输入、API key、token 或实名信息。

## 配置

在 `.env.example` 增加非敏感策略配置：

```text
TRAVEL_RAIL_CONNECTION_MATCHER_V2=true
TRAVEL_RAIL_MIN_TRANSFER_MINUTES=45
TRAVEL_RAIL_MAX_TRANSFER_WAIT_MINUTES=360
```

配置解析失败时使用安全默认值并记录配置错误；不得默认为 0 分钟换乘。

## 主要文件范围

- `backend/app/services/rail_connection_matcher.py`（新增）
- `backend/app/services/planner.py`
- `backend/app/services/location_resolver.py`（仅在需要稳定 station id/code 时修改）
- `backend/app/data_sources/rail_providers.py`（只补稳定事实字段/去重支持，不改变授权边界）
- `backend/app/tests/test_rail_connection_matcher.py`（新增）
- `backend/app/tests/test_planning_rules.py`
- `backend/app/tests/test_api.py`
- `.env.example`

## 非目标

- 不实现隔夜或次日中转。
- 不新增多次铁路换乘。
- 不修改 API schema version、公共字段和前端类型。
- 不引入新的铁路 Provider 或未经授权数据源。
- 不使用 LLM 生成、补齐或修改车次、时间、票价和余票。
- 不恢复规则估算接驳。

## 验收标准

- 第二程最早两个 offer 均不可连接、后续 offer 可连接时，必须生成有效中转候选。
- 北京西 G502 14:12 到达 + D6649 14:58 发车通过 45 分钟门槛。
- 44 分钟连接被拒绝，45 分钟连接通过；最大等待时间边界行为确定。
- 同站换乘不调用地图 Provider，跨站换乘没有真实路线时不得生成计划。
- Provider 有事实但无安全连接时返回 `RAIL_CONNECTION_NOT_FOUND`，不误报缺票价。
- 候选匹配不增加 Provider 查询次数，不因扩大候选池突破现有 QPS 控制。
- 正常直达铁路、航班、空铁联运、NO_MATCH、重算和跳转无回归。
- API schema 仍为 V1.17，schema export 无非预期 diff。

## 验证命令

- `.\.venv\Scripts\python -m pytest backend/app/tests/test_rail_connection_matcher.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_planning_rules.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_api.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests`
- `.\.venv\Scripts\python scripts/export_schemas.py` 后检查 `schemas/` diff
- `.\.venv\Scripts\python scripts/check_real_api_config.py --tier public`
- `.\.venv\Scripts\python scripts/live_smoke_real_apis.py --tier public`

## 风险与回滚

- 候选量增长通过二分查找、最大等待窗口、验证后上限和任务级缓存控制。
- 使用 `TRAVEL_RAIL_CONNECTION_MATCHER_V2` 灰度；关闭后回到旧 matcher，不影响数据结构。
- 新模块不做数据库迁移，回滚不需要重写历史响应。
- 回滚时保留新增诊断日志；禁止以降低安全换乘门槛或恢复模拟数据作为回滚手段。
