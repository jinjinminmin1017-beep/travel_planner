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

# ARC-20260714-02 修复高德公交空费用导致异步规划崩溃

来源：2026-07-14 真实规划失败诊断。任务 `job_65889cd392e0`，请求 `req_0e9d3df67a7d`。

完成状态：已完成。完成时间：2026-07-14 22:06:23 +08:00。代码提交：`5da3564859b66e1d33c7f0ffab4dbc878bb52f81`。

实现摘要：高德公交/地铁空费用现在保留为 `estimated_cost=None`，距离、时长和步行距离事实不丢失；非法金额结构统一转换为 `MAP_ROUTE_RESPONSE_INVALID`，地图 Provider 边界会隔离字段类型异常并继续后备 Provider 或其他接驳方式。公共 API、Schema V1.17、数据库和前端类型均未改动。

## 背景与证据

- 高德公交/地铁路线接口 `/v3/direction/transit/integrated` 返回 `status=1`，并返回 5 条 `transits`，说明路线查询本身成功。
- 第一条路线的原始费用字段为 `cost: []`，表示该路线没有可直接消费的费用值。
- `AmapRouteProvider._parse_payload()` 将 `first.get("cost")` 交给 `_yuan_to_money()`；当前实现直接执行 `float(value)`，对空数组触发 `TypeError`。
- `estimate_route_with_enabled_provider_result()` 未捕获 `TypeError`，异常越过地图 Provider 和本地接驳边界，最终由异步任务总兜底转换为通用 `planning_status=FAILED`。
- 本次铁路中转 Provider 已返回可用事实，地点坐标和出租车路线也已解析成功；失败不是地址歧义、12306 全量无结果或前端轮询超时。
- 当前 `test_map_providers.py` 只覆盖字符串费用 `cost: "5"`，没有覆盖空数组、缺失值或异常结构。

## 开发目标

- 兼容高德真实响应中的空费用字段，费用未知不得阻断已验证的距离、时长和路线。
- 金额转换禁止使用 `float`，统一使用 `Decimal` 进行元到分转换。
- 单个接驳方式响应结构异常时只淘汰该方式或将可选费用标为未知，不得击穿整个规划任务。
- 保持 API schema V1.17、数据库结构和前端类型不变。

## 开发任务 A：费用字段规范化

1. 修改 `backend/app/data_sources/map_providers.py` 的 `_yuan_to_money()`，建立明确输入规则：
   - `None`、空字符串、空数组返回 `None`，语义为“费用未知”。
   - 合法整数、数字字符串和可安全转换的十进制值使用 `Decimal(str(value))` 转换为分。
   - 禁止继续使用 `float` 处理金额。
   - 非空数组、对象、布尔值、非有限值、负数或非法字符串不得任意取值或默认为 0；转换为结构化 Provider 响应错误。
2. 费用未知时保留 Provider 返回且已通过校验的距离、时长和步行距离。
3. 不得把 `cost=[]` 显示为 0 元，不得生成模拟费用或规则估算费用。
4. 驾车 `taxi_cost` 与公交 `transits[].cost` 复用同一安全金额解析规则。

## 开发任务 B：Provider 故障隔离

1. 将响应字段类型错误统一包装为 `MapProviderError`，错误码使用 `MAP_ROUTE_RESPONSE_INVALID`。
2. `estimate_route_with_enabled_provider_result()` 对适配器边界增加必要的 `TypeError`、`KeyError` 防御，转换为 Provider 失败结果后继续尝试兼容的备用 Provider；不得让异常直接退出规划器。
3. 某种接驳方式失败时，`build_local_transfer_options()` 继续处理其他方式：
   - 出租车成功、公交费用未知时，至少保留出租车；公交距离和时长有效时可保留公交并将费用置空。
   - 只有所有允许方式均无有效路线时，才返回 `MAP_TRANSFER_UNAVAILABLE` 并淘汰该门到门候选。
4. 异步任务总兜底继续保留，但正常 Provider 数据异常必须在 Provider 层转成结构化失败，不能只留下 `missing_components=["travel_plan"]`。
5. 日志只记录 Provider、字段路径、实际类型和错误码；不得记录完整原始响应、API key 或带密钥的请求 URL。

## 开发任务 C：测试与回归

1. 在 `backend/app/tests/test_map_providers.py` 增加费用解析矩阵：
   - `"5"`、`5`、`"5.25"` 正确转换为分。
   - `None`、`""`、`[]` 返回 `None`。
   - `{}`、非空数组、布尔值、负数、非数字字符串返回 `MAP_ROUTE_RESPONSE_INVALID`，且不会抛出未捕获异常。
2. 增加高德公交成功响应 `transits[0].cost=[]` 回归用例，断言距离、时长仍被保留。
3. 在 `backend/app/tests/test_local_transfer_engine.py` 增加单方式异常隔离：一个地图方式响应无效时，其他已验证方式仍可形成 `LocalTransferSegment`。
4. 增加异步规划回归：模拟本次空费用响应，轮询终态不得为系统异常 `FAILED`；若仍存在铁路候选，应返回 `COMPLETE`、`PARTIAL` 或基于约束的 `NO_MATCH`。
5. 现有正常驾车、步行、公交、地图备用 Provider、铁路中转和 API 全量测试不得回归。

## 主要文件范围

- `backend/app/data_sources/map_providers.py`
- `backend/app/services/local_transfer_engine.py`（仅在需要补充单方式隔离时修改）
- `backend/app/tests/test_map_providers.py`
- `backend/app/tests/test_local_transfer_engine.py`
- `backend/app/tests/test_api.py` 或规划集成测试文件

## 非目标与合同影响

- 不修改 API URL、请求字段、响应字段或 schema version。
- 不修改数据库结构，不需要迁移。
- 不修改前端，不新增费用展示字段。
- 不启用新的地图 Provider，不恢复规则估算接驳。
- 不把未知费用写成 0，不使用 LLM 推测公交或出租车费用。

## 验收标准

- 高德返回 `status=1`、有效 `transits` 且 `cost=[]` 时，解析过程不抛出 `TypeError`。
- 空费用被表示为 `estimated_cost=None`，距离、时长和路线来源保持真实 Provider 事实。
- 单个公交/地铁方式费用或响应结构异常不会终止整个异步规划任务。
- 非法费用结构生成 `MAP_ROUTE_RESPONSE_INVALID`，日志不包含 API key 和完整响应。
- 金额转换路径不再使用 `float`，元到分精度测试通过。
- 本次复现场景不再由 `_yuan_to_money()` 导致通用 `FAILED`。

## 验证命令

- `.\.venv\Scripts\python -m pytest backend/app/tests/test_map_providers.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_local_transfer_engine.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_api.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests`
- `.\.venv\Scripts\python scripts/export_schemas.py` 后确认 `schemas/` 无非预期 diff

## 风险与回滚

- 将未知费用保留为 `None` 可能使部分计划缺少接驳费用，但比伪造 0 元或终止规划更符合事实边界；推荐和总价逻辑必须沿用现有“可空费用”语义。
- 扩大异常捕获范围可能隐藏适配器缺陷，因此必须先记录 `MAP_ROUTE_RESPONSE_INVALID`，且只在 Provider 边界捕获明确的字段类型异常。
- 修复只涉及响应解析，无数据库和公共合同变化；紧急回滚可恢复旧解析器，但应优先通过功能级回退禁用公交费用消费，不能恢复 `float` 金额计算或模拟费用。
