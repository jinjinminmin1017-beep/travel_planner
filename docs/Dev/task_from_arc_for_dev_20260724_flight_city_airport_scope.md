# ARC-20260724-01 航班城市查询范围与实际机场归一化

来源：用户反馈“最后一次规划仍没有航班选项，但春秋航空官网有符合班次”，架构核查日期 2026-07-24。

状态：已完成（2026-07-24，代码提交 `03c8232`）。

## 1. 已确认问题

- 问题任务：`job_2905e377ffef` / `req_1665ef7e5c04`，上海嘉定格林公馆到大连海事大学，2026-07-25 出发。
- 春秋接口 `SHA -> DLC` 返回 HTTP 200；原始证据 `fltraw_124e4ef88dbd` 含 4 个航班：9C8843、9C8977、9C7157、9C8981。
- 响应城市码为 `SHA -> DLC`，实际机场码为 `PVG -> DLC`。
- 当前解析器把请求 `origin_iata=SHA` 同时当城市码和具体机场码，因 `PVG != SHA` 丢弃全部航班，错误产出 `FLIGHT_PROVIDER_EMPTY`。
- 上海机场目录中内部虹桥种子与 OurAirports 虹桥记录未合并，前二候选被虹桥重复占用，浦东被挤出。
- 只删除机场相等校验会产生错误事实：计划可能显示接驳到虹桥，但航班实际从浦东出发。

## 2. 开发目标

1. 分离城市查询码、实际机场 IATA 和允许机场集合。
2. 每个 Provider 只声明最小 `query_scope=CITY|AIRPORT`，由代码固定且不能被 ENV 覆盖。
3. 对所有航司和所有航段实施“实际机场优先”：航班段与全部接驳只使用响应实际机场；春秋 `PVG -> DLC` 仅作为回归样本。
4. 机场目录先规范化去重，再排序和截断。
5. 非空上游候选全部解析失败时报告解析失败，不再伪装成空结果。
6. 保持外部 API schema `1.17` 不变，不进行数据库迁移。

## 3. 后端任务

### 3.1 内部查询范围模型

- 在航班 Provider 层新增或重构内部 `FlightSearchScope`，至少包含：
  - 起终点城市名；
  - Provider 城市查询码；
  - 允许的起终点机场 IATA 集合；
  - 日期、人数、币种、直飞偏好和结果上限。
- Provider 增加代码常量 `query_scope: CITY | AIRPORT`，固定映射：
  - `SpringAirlinesPublicQueryProvider = CITY`
  - `HainanAirlinesPublicQueryProvider = CITY`
  - `QingdaoAirlinesPublicQueryProvider = AIRPORT`
  - `BrowserAirlineFlightProvider = AIRPORT`，但东航继续禁用
- `query_scope` 不进入 `.env`，不实现 capability version、evidence registry 或运行时自动探测。
- 新增航司未显式声明 `query_scope` 时，不加入航班查询列表。
- 春秋使用城市查询码构造 `DepCityCode/ArrCityCode`，城市查询时保持 `DepAirportCode/ArrAirportCode` 为空。
- 海航按城市范围查询；青岛航空和浏览器 Provider 按单机场查询；禁止把春秋规则复制到全部航司。
- 缓存键加入查询粒度、城市码和机场过滤集合。

### 3.2 机场目录规范化

- 修正交通目录生成/合并规则：
  - 优先按 IATA/ICAO 合并；
  - 无代码内部种子通过受控映射补齐或并入对应导入记录；
  - 名称、别名和坐标仅作辅助证据。
- `airport_candidates_for_location/city()` 在 top-N 前完成去重。
- 只让有 IATA、可验证坐标和商业客运资格的机场进入规划候选。
- 增加按 IATA 返回 canonical `AirportCandidate` 的稳定接口。
- 上海候选必须包含且只包含一次 `SHA`、`PVG`；军用机场和无 IATA 记录不得占用候选名额。

### 3.3 所有 Provider 的实际机场规范化

- 每个 Provider 的每一个航段都必须从响应提取实际起降机场 IATA。
- 当前响应不含实际机场时，只允许通过另一已批准、能唯一关联同一航班/日期/航段的事实源补全；否则拒绝该 offer。
- 禁止从请求机场、城市默认机场、最近机场或候选排序结果推断实际机场。
- 实际机场必须属于请求城市/允许集合，并能映射到 canonical airport。
- 春秋回归适配需要同时读取并区分：
  - `DepartureCode/ArrivalCode`：城市范围；
  - `DepartureAirportCode/ArrivalAirportCode`：实际机场。
- 通过后将实际 IATA 写入 `FlightOfferSegment`；不得用请求城市码覆盖响应实际机场。

- 保留当前航班号、时刻、舱位、价格和 evidence 校验；新增丢弃 reason code 统计。
- `Route` 非空但 offer 为零时返回 `FLIGHT_PARSER_REJECTED_ALL` 或 `FLIGHT_PROVIDER_INVALID_RESPONSE`，不得返回 `FLIGHT_PROVIDER_EMPTY`。
- 只有有效业务响应明确没有 route/flight 时才返回 `EMPTY`。

### 3.4 Planner 编排与门到门事实

- 将当前固定机场对循环改为按 Provider `query_scope` 编排：
  - 城市范围 Provider：每个 Provider/城市对查询一次；
  - 机场范围 Provider：查询规范化后的允许机场组合。
- 收到 offer 后按每个航段的实际起降 IATA 反查机场节点。
- 首程接驳连接第一航段实际起飞机场，末程接驳连接最后航段实际到达机场。
- 中转相邻航段实际机场不同，必须生成并验证跨机场接驳和最小换乘时间；无法完成时 fail-closed。
- 机场目录、坐标或地图路线不足时 fail-closed，禁止回退到查询机场。
- 按航司、航班号、日期、实际机场和时刻去重。
- 保持最终计划数量限制，但不能在机场规范化前截断。
- 查询返回原始候选但解析失败时，默认铁路+航班请求返回 `PARTIAL`；真正空结果维持现有 `EMPTY` 语义。

### 3.5 可观测性

- 每次 Provider 解析记录原始候选数、规范化 offer 数、实际机场集合、丢弃 reason code 计数、parser version 和 evidence id。
- 文本日志不写完整正文或敏感 header。
- 若完整交换证据表尚未实现，本任务至少继续使用已有脱敏 raw snapshot，并保证解析诊断可关联 evidence id。

## 4. 目标文件

- `backend/app/data_sources/flight_providers.py`
- `backend/app/data_sources/browser_flight_providers.py`
- `backend/app/services/location_resolver.py`
- `backend/app/services/planner.py`
- `backend/app/data_sources/transport_catalog_providers.py`
- 既有交通目录生成脚本
- `backend/app/data/transport_nodes.json`（只允许通过生成流程更新）
- `backend/app/tests/test_flight_providers.py`
- `backend/app/tests/test_transport_catalog_providers.py`
- `backend/app/tests/test_planning_rules.py`
- `backend/app/tests/test_api.py`
- 新增最小脱敏 fixture（只保留回归所需字段）

## 5. 验收标准

- 问题响应的最小 fixture 解析出 4 个 `PVG -> DLC` 春秋 offer。
- 春秋、海航 `query_scope=CITY`；青岛航空、东航 Browser `query_scope=AIRPORT`；ENV 无法覆盖。
- `CITY` Provider 每个城市对只查询一次，`AIRPORT` Provider 查询规范化后的合法机场组合。
- 所有航班计划的每一航段与接驳均使用响应实际机场；缺失实际机场时不生成计划。
- 问题 fixture 至少可构造一个完整门到门航班计划，响应实际机场为浦东，因此接驳目标自然为浦东。
- 不出现任何“接驳机场与实际起降机场不一致”的事实冲突。
- 中转跨机场时存在显式、可验证且时间可行的接驳；否则方案被阻断。
- 上海机场候选去重后包含 `SHA` 与 `PVG`，每个一次。
- 非空 Route 全部被拒绝时 outcome 为解析失败；空 Route 才是 `EMPTY`。
- 等价 API 规划结果包含真实航班 plan，航班入口可从既有 `plans` 推导为可用。
- 海航、青岛航空、铁路、重试、舱位重算和外部 schema 无回归。

## 6. 建议验证命令

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_transport_catalog_providers.py backend/app/tests/test_planning_rules.py backend/app/tests/test_api.py -q
.\.venv\Scripts\python scripts/export_schemas.py
git diff --exit-code -- schemas
npm --prefix frontend test
npm --prefix frontend run typecheck
git diff --check
```

真实 smoke 仅允许低频调用已批准的公开匿名来源；遇到限流、挑战或协议变化立即 fail-closed，不绕过风控。

## 7. 风险与回滚

- 不允许以删除 `PVG != SHA` 校验作为单点修复；必须同时完成实际机场反查和接驳重建。
- 机场规范化、`query_scope` 编排、Provider 解析、Planner 接驳分提交实现，但查询编排和实际机场建计划必须作为同一安全发布单元启用。
- 回滚时春秋非空但无法解析的响应显示“暂不可确认”，不得恢复错误的“没有航班”。
- 不修改外部合同、不迁移数据库、不启用尚未通过门禁的航司。

## 8. 完成记录

- [x] 新增 `FlightSearchScope`，分离城市查询码、允许机场集合与实际响应机场。
- [x] 固定春秋/海航为 `CITY`，青岛航空/东航 Browser 为 `AIRPORT`；未声明 scope 的新 Provider 不进入聚合列表。
- [x] 城市 Provider 每个城市对只查询一次；机场 Provider 遍历 canonical 机场组合，缓存键包含查询粒度、城市码与机场过滤集合。
- [x] 春秋解析器分别校验城市码与实际机场；海航、青岛航空和 Browser Provider 保持各自查询语义。
- [x] 所有 Provider 在非空候选全部被拒绝时返回 `FLIGHT_PARSER_REJECTED_ALL`，并记录候选数、offer 数、实际机场、reason code、parser version 与 evidence id。
- [x] 内部机场种子通过受控映射补齐 IATA；机场候选在 top-N 前按 IATA canonical 化，上海稳定返回一次 `SHA` 和一次 `PVG`。
- [x] Planner 使用每个航段的实际机场构建首末程接驳；跨机场中转必须生成可验证接驳并满足时间门槛，否则阻断方案。
- [x] 新增脱敏最小问题 fixture，验证 4 个 `PVG -> DLC` 春秋 offer 及浦东首程接驳。
- [x] 外部 API schema 保持 `1.17`，Schema 导出无差异；无需数据库迁移或前端字段同步。
- [x] 后端全量 240 项、前端 helper 14 项、TypeScript、Expo 三平台导出、Python compileall 与 `git diff --check` 均通过。
