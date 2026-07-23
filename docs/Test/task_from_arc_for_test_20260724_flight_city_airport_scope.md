# TEST-20260724-01 航班城市查询范围与实际机场归一化验收

来源：`docs/Dev/task_from_arc_for_dev_20260724_flight_city_airport_scope.md`。

状态：待测试。

## 1. Provider 单元测试

- 固定断言 `query_scope`：
  - 春秋、海航为 `CITY`；
  - 青岛航空、东航 Browser 为 `AIRPORT`。
- ENV 不能添加或覆盖 `query_scope`。
- adapter 未声明合法 `query_scope` 时，不得加入启用 Provider 列表。
- 使用脱敏最小 fixture 模拟春秋城市查询：
  - 请求城市码 `SHA -> DLC`；
  - 响应城市码 `SHA -> DLC`；
  - 响应实际机场 `PVG -> DLC`；
  - 航班 9C8843、9C8977、9C7157、9C8981。
- 断言解析得到 4 个 offer，所有 segment 实际机场均为 `PVG -> DLC`。
- 响应城市码不匹配时拒绝，并记录 `FLIGHT_CITY_CODE_MISMATCH`。
- 实际机场不属于请求城市或不在显式允许集合时拒绝，并记录 `FLIGHT_AIRPORT_OUT_OF_SCOPE`。
- 非空 Route 因字段错误全部被拒绝时，不得返回 `EMPTY`；应为 `FLIGHT_PARSER_REJECTED_ALL/FLIGHT_PROVIDER_INVALID_RESPONSE`。
- 有效空 Route 才返回 `FLIGHT_PROVIDER_EMPTY`。
- 缓存键区分城市查询、机场查询和不同机场过滤集合。
- 海航保持城市查询；青岛航空和浏览器 Provider 保持单机场查询；每一航段均输出响应实际机场。
- 任一 Provider 响应缺少实际机场，且没有已批准第二事实源可唯一补全时，不得生成 offer。

## 2. 机场目录测试

- 上海内部种子和 OurAirports 重复记录合并为 canonical airport。
- `airport_candidates_for_city("上海")` 去重后包含 `SHA`、`PVG`，各一次。
- `airport_candidates_for_location("上海嘉定格林公馆")` 不因虹桥多来源重复而挤掉浦东。
- 军用机场、无 IATA 或无可验证坐标的记录不占用航班规划候选配额。
- 按 IATA 反查 `PVG`、`SHA`、`DLC` 返回正确城市、名称和坐标。
- top-N 在去重和资格门禁之后执行。

## 3. Planner 集成测试

- 对所有 Provider 的 Planner 集成路径验证统一不变量：
  - 首程接驳终点等于第一航段响应实际起飞机场；
  - 末程接驳起点等于最后航段响应实际到达机场；
  - 查询参数中的机场不得覆盖响应实际机场。
- 使用问题路线等价请求和 fake Provider 返回 `PVG -> DLC` offer：
  - 生成真实航班计划；
  - 航班 segment 为 `PVG -> DLC`；
  - 起点本地接驳目的地为浦东机场；
  - 终点本地接驳起点为大连周水子机场。
- 禁止出现查询候选为虹桥后仍把 `PVG` 航班连接到虹桥的计划。
- 实际机场无法反查、无坐标或地图接驳失败时，计划 fail-closed 并有明确 SourceFailure。
- 同一航班从多个查询路径返回时只生成一个候选。
- 城市范围 Provider 每个城市对只调用一次，不按机场组合重复调用。
- 机场范围 Provider 只查询规范化后的合法机场组合。
- 上海到大连场景中，春秋和海航各查询一次城市对；青岛航空按 `SHA/PVG -> DLC` 合法机场组合查询，不因第一个机场空结果提前结束。
- 中转相邻航段使用各自响应实际机场；机场不同时必须生成跨机场接驳并验证可行时间，否则阻断。

## 4. API 与状态语义

- 等价 `/api/travel/plan` 或异步最终响应中有航班计划时，`plans` 包含真实 FLIGHT segment，既有航班入口可推导为可用。
- 铁路可用、春秋非空响应解析失败时为 `PARTIAL`，并显示“暂不可确认”，不得显示“没有航班”。
- 所有航班 Provider 有效空结果时允许 `COMPLETE + FLIGHT_PROVIDER_EMPTY`。
- 外部 schema version 保持 `1.17`，无新增字段，schema export 无 diff。
- 显式排除航班时不查询、不产生航班失败。
- 旧响应、铁路规划、来源重试、航班舱位重算和预订跳转无回归。

## 5. 人工验收

- 在批准的低频真实 smoke 中重放同城市/日期查询时，若春秋仍返回对应班次：
  - App 航班入口可用；
  - 方案显示浦东到大连；
  - 门到门首段前往浦东机场；
  - 航班号、时刻、价格和舱位均来自同一 evidence。
- 若实时库存已变化，不以“必须仍有 4 班”为门禁；人工验收以当前响应和解析一致性为准，自动回归使用固定脱敏 fixture。
- 真实 smoke 遇到 429、验证码、挑战或协议变化立即结束，不做绕过。

## 6. 建议执行

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_transport_catalog_providers.py backend/app/tests/test_planning_rules.py backend/app/tests/test_api.py -q
.\.venv\Scripts\python scripts/export_schemas.py
git diff --exit-code -- schemas
npm --prefix frontend test
npm --prefix frontend run typecheck
git diff --check
```

## 7. 通过标准

- 自动测试全部通过。
- 问题 fixture 稳定解析出实际 `PVG -> DLC` offer。
- 所有直飞、中转和跨机场计划的接驳机场与每个航段响应实际机场一致。
- 非空解析失败和真实空结果的状态语义完全区分。
- 无虚构航班、无错误机场替换、无外部合同变化。
