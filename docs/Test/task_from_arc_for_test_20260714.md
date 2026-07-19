# ARC-TEST-20260714-01 铁路中转完整候选匹配测试

来源：架构任务，2026-07-14。

完成状态：待测试。

关联开发任务：`docs/Dev/task_from_arc_for_dev_20260714.md`。

## Matcher 单元测试

- 第二程前两个 offer 都早于第一程到达，但后续 offer 满足换乘门槛：必须返回后续连接。
- 使用北京西固定数据：G502 14:12 到达、D6649 14:58 发车，等待 46 分钟，应通过 45 分钟门槛。
- 44 分钟连接拒绝，45 分钟连接通过。
- 第二程在第一程到达前发车时拒绝并计入 `rejected_departed_before_arrival`。
- 等待超过 `max_transfer_wait_minutes` 时拒绝；等于上限时行为必须有固定断言。
- offer 输入无序时结果仍稳定；重复 offer 按稳定事实键去重。
- 第一/二程车次相同且不具备已验证直通语义时不得生成伪换乘。
- 缺票价、缺席别、时间无时区或车站身份不一致时返回明确拒绝原因，不抛未捕获异常。
- 多个有效连接按确定性规则排序，相同输入重复运行结果一致。
- 候选上限只在验证后生效，不得阻止后续合法连接进入匹配阶段。

## 同站与跨站测试

- station id/code 相同：识别为同站换乘，不调用地理编码、地图路线或 `taxi()`。
- 展示名称不同但 station code 相同：仍识别为同站并完成去重。
- 名称相同但 station code 冲突：不得猜测同站，进入跨站验证。
- 跨站路线验证成功：使用 Provider 返回的真实接驳耗时计算安全门槛。
- 跨站路线空结果、歧义、超时、限流：连接退出正常候选，且不生成规则估算数字。
- 同站连接总时长包含两段车次之间的真实等待时间。

## Planner 集成测试

- Provider 返回完整第一、二程 offer 后，planner 将完整集合交给 matcher，不再使用连接前 `[:2]` 截断。
- 多个中转站均有候选时先完成验证再全局排序，不由遍历顺序决定前三个方案。
- 汉口缺票价、北京西存在有效连接时，北京西方案仍能生成，汉口错误不得覆盖整个中转类型。
- Provider 两段均成功但无安全连接时，返回 `RAIL_CONNECTION_NOT_FOUND`。
- Provider 确实空结果或缺票价时，保留对应 Provider 错误码。
- 同站地图能力关闭时，北京西站内换乘仍可生成；跨站计划仍必须依赖真实地图能力。
- 关闭 `TRAVEL_RAIL_CONNECTION_MATCHER_V2` 时旧路径可运行，开启时使用新 matcher。

## API 与状态回归

- 异步任务存在有效铁路中转时不得因候选提前截断返回 FAILED。
- 无连接、Provider 失败和用户硬约束无匹配三种状态及文案不得混淆。
- `TravelPlanResponse`、`RailSegment` 和前端既有类型不新增必填字段，schema version 保持 V1.17。
- 新匹配器不增加同一站点对的 Provider 查询次数，不突破现有 QPS/缓存策略。

## 可观测性断言

- 日志包含第一/二程 offer 数量、检查组合数、各拒绝原因数量、有效和选中连接数量。
- 日志能通过 request/trace/correlation id 关联任务。
- 日志不包含完整用户输入、API key、token 或实名信息。

## 回归命令

- `.\.venv\Scripts\python -m pytest backend/app/tests/test_rail_connection_matcher.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_planning_rules.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests/test_api.py`
- `.\.venv\Scripts\python -m pytest backend/app/tests`
- `.\.venv\Scripts\python scripts/export_schemas.py` 后检查 `schemas/` diff
- `.\.venv\Scripts\python scripts/check_real_api_config.py --tier public`
- `.\.venv\Scripts\python scripts/live_smoke_real_apis.py --tier public`

## 通过标准

- 北京西后续可行车次不再因第二程前两个 offer 过早而漏检。
- 45 分钟安全门槛和最大等待窗口边界稳定。
- 同站不依赖地图，跨站不允许虚构接驳。
- Provider、连接匹配、接驳和约束四类失败可独立诊断。
- 全量回归通过，schema 无非预期变化。
