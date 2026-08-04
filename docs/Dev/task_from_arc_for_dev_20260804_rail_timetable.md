# 开发任务：本地铁路时刻表快照与实时核票

> 来源：`docs/ARCHITECTURE.md`“本地铁路时刻表快照与实时核票架构（2026-08-04）”。
> 本文只拆分开发任务，不授权绕过验证码、限流或访问控制。

## 目标

- 首次在本地 SQLite 补全全国 D0～D+14 的 G/D/C 完整经停时刻，之后每天滚动更新，并可断点续跑、幂等补跑。
- 使用本地快照完成直达和一次换乘候选搜索。
- 按站点对分组调用 FlyAI 核验余票、价格、席别和跳转链接。
- 修正站点候选逻辑：明确地点语义优先，`hub_rank` 只作弱排序特征。
- 通过功能开关灰度上线，并保留现有铁路规划路径作为回滚。

## P0-1：冻结边界与配置

涉及文件：

- `backend/app/data_sources/config_loader.py`
- `.env.example`
- `docs/PROJECT_INDEX.md`

任务：

- 新增 `TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED`，控制快照读取/导入能力。
- 新增 `TRAVEL_RAIL_LOCAL_ROUTING_ENABLED`，控制 Planner 是否使用本地候选路线。
- 新增每日刷新开关、15 天窗口、执行时间和历史批次保留期配置；调度配置默认关闭。
- 两个开关默认关闭；值解析沿用现有配置规范。
- 明确本地快照不注册为票务事实 Provider，不输出价格、余票或 redirect。
- 在项目索引登记新增模块、脚本与测试入口。

验收：关闭开关时，启动和现有铁路规划行为不变。

## P0-2：完成 12306 低频导入 POC

建议新增：

- `backend/app/data_sources/rail_12306_timetable_provider.py`
- `scripts/import_12306_timetable.py`

任务：

- 复用现有 `station_name.js` 站点目录和 telecode。
- 验证“按日期/站点发现车次”和“按内部车次标识查询完整停站”两个当前可用响应。
- 禁止使用日期停留在 2022 年的 `train_list.js` 作为当前车次清单。
- 支持 `--mode bootstrap|refresh`、`--date-from`、`--days`（默认 15）、`--interval-seconds`、`--resume`、`--dry-run`。
- `bootstrap` 按 D0～D+14 从近到远补全；`refresh` 完整导入新 D+14，并对 D0～D+13 执行车次发现差异校正。
- 默认单线程、1～2 秒间隔；暂时网络错误有限指数退避，验证码/429/访问限制立即暂停并写 checkpoint。
- 对响应结构做严格解析，记录响应哈希、解析版本和脱敏错误；不记录会话凭据。
- 只保留 G/D/C，按 `(service_date, train_no_internal)` 去重。

验收：用获准低频样例完成至少一个日期的小范围发现、详情查询、中断与恢复；不得自动绕过挑战。

## P0-3：新增快照表与批次机制

建议新增/调整：

- 数据库 migration
- `backend/app/services/rail_timetable_store.py`
- 对应 persistence 初始化和测试 fixture

任务：

- 新增 `rail_timetable_batch`、`rail_service` 与 `rail_stop_time`，字段、唯一约束和索引严格遵循架构文档。
- `rail_timetable_batch` 按服务日记录 STAGING/ACTIVE/FAILED/RETIRED、统计、开始/完成时间和解析版本；同一服务日只能有一个 ACTIVE 批次。
- `rail_service` 使用 `(batch_id, train_no_internal)` 唯一约束，使 STAGING 与上一 ACTIVE 数据可以同时存在。
- staging 写入完成后校验并原子激活；失败批次不得覆盖 active 快照。
- 差异刷新允许复用摘要指纹未变化车次的停站数据；新增、取消或摘要变化必须反映在完整 STAGING 批次中，禁止直接向 ACTIVE 追加。
- 实现按唯一键幂等 upsert，保证重复导入和 resume 不产生重复行。
- 时间使用 Asia/Shanghai 服务日期加独立到达/发车 day offset；数据库时间类型与序列化规则保持一致。
- 提供覆盖日期、新鲜度、服务数和停站数查询。

验收：迁移可前向执行；重复导入结果稳定；失败批次不影响上一有效批次。

## P0-4：实现本地路线搜索

建议新增：

- `backend/app/services/rail_route_search.py`

任务：

- 定义内部 `RailScheduleCandidate`，包含两段以内的服务、站序、绝对到发时间、总耗时和换乘信息，不包含票务事实。
- 直达搜索要求同一服务且出发站序小于到达站序。
- 一次换乘搜索要求第一段到达时间加安全窗口不晚于第二段发车时间。
- 支持跨日但限制搜索日期、总时长、换乘等待、换乘站数和返回候选数。
- 排序综合直达优先、总耗时、等待、时间偏好、站点相关性和去车站成本。
- 查询必须命中设计索引，禁止加载全表后在 Python 中建立全国图。
- 输出搜索诊断：扫描/命中服务数、候选数、裁剪原因和耗时。

验收：fixture 覆盖方向、跨日、始终站空时间、一次换乘和无解；达到架构性能门禁。

## P0-5：修正站点候选与截断规则

涉及文件：

- 现有地点解析、站点选择与 `hub_rank` 排序模块
- `backend/app/services/planner.py`

任务：

- 为候选记录匹配类型：明确站名、区县强匹配、城市内站点、扩展枢纽。
- 先保留强匹配，再对剩余名额使用相关性、距离和 `hub_rank` 排序；不得全局排序后统一截断。
- “宜兴”必须保留宜兴站；无锡站、无锡东站只能作为扩展候选。
- 对同名地点、城市边界和用户明确指定“某某站”建立确定性规则。
- 保持站点数量有界并输出候选来源和截断原因到诊断日志。

验收：宜兴回归用例通过，现有主要城市多站搜索不发生无界扩张。

## P0-6：实现 FlyAI 分组核票器

建议新增：

- `backend/app/services/rail_inventory_verifier.py`

涉及文件：

- `backend/app/data_sources/fliggy_flyai_provider.py`
- 现有 RailOffer 映射与缓存层

任务：

- 按 `(service_date, origin_station, destination_station)` 对候选分组，一次查询匹配同组多个车次。
- 用日期、车次号、起终站和时间容差关联候选，拒绝模糊到无法唯一关联的结果。
- 内部状态至少区分 `SCHEDULE_CANDIDATE`、`AVAILABLE`、`SOLD_OUT`、`NOT_ON_SALE`、`PROVIDER_UNAVAILABLE`。
- 仅 `AVAILABLE` 且价格、票务语义和 `jumpUrl` 完整时允许发布。
- 每个 job 设置分组数、总时长和重试预算；无票进入下一候选组，确定性错误不重试。
- 复用现有 QPS、single-flight、TTL 缓存和来源熔断，不建立第二套并发控制。

验收：同一站点对多个候选只发一次外部请求；所有失败路径均 fail-closed。

## P0-7：接入 Planner 并支持回滚

涉及文件：

- `backend/app/services/planner.py`
- 铁路路线构建、持久化和 redirect 关联模块

任务：

- 开关开启且快照覆盖有效时：解析站点 -> 本地搜索 -> 排序 -> 分组核票 -> 发布已验证计划。
- 快照关闭、过期或目标日期不覆盖时，回退现有实时路线发现路径；本地空结果和快照不可用必须区分。
- 不改变现有外部 API schema；不向前端发送未核票的参考候选。
- 保持既有 fingerprint、价格、席别与 redirect 的一致性校验。
- 防止直达、换乘和混合规划重复核验同一站点组。

验收：开关关闭行为等价；开启后典型铁路规划实际 FlyAI 查询不超过 3 组。

## P0-8：每日滚动刷新、补跑与可观测性

任务：

- 增加快照覆盖、新鲜度、批次状态、服务/停站数和导入异常指标。
- 增加本地搜索 P50/P95/P99、候选数、核票分组数、外部调用数和预算耗尽原因。
- 增加每日滚动刷新任务：窗口固定为 D0～D+14，移出过期日期、完整导入新 D+14，并差异校正 D0～D+13。
- 新增 Windows Task Scheduler 安装/检查/卸载脚本；其他部署环境在运维文档提供等价 cron/systemd timer 示例，不在 FastAPI 内启动永久后台循环。
- 刷新默认由显式调度配置触发，不在 Web 请求内抓取；错过执行或失败后，下次运行按新鲜度自动 catch-up。
- 每个服务日保留 ACTIVE 和至少一个上一成功批次；按配置清理过期日期与更老 RETIRED 批次。
- 为未覆盖日期、过期快照和失败批次提供可读诊断。
- 补充运维说明：首次导入、resume、dry-run、批次激活、关闭开关和回滚。

验收：运维人员能从日志/状态判断“无车”“快照不可用”“未开售”“无票”和“FlyAI 故障”。

## 开发顺序与依赖

1. P0-1 与 P0-2 可并行验证，但 POC 未证明当前响应可稳定解析前，不提交全量导入。
2. P0-3 完成后才能实现可运行的 P0-4。
3. P0-5 可独立开发，但必须在 Planner 集成前完成。
4. P0-6 复用现有 FlyAI 稳定性门禁；若 CLI 仍未认证，仅使用 fixture 完成开发，不宣称真实可用。
5. P0-7 最后接入，默认关闭功能开关，通过测试与 benchmark 后灰度启用。

## 完成定义

- 所有 P0 任务及对应测试通过，migration、首次 15 天建库、每日滚动刷新、功能开关、回滚和项目索引齐全。
- 本地候选与实时票务事实边界在类型、日志和接口输出中均不可混淆。
- 不修改 `docs/API_CONTRACT.md`；若开发过程中决定展示未核票候选，必须暂停并先发起新的架构/API 评审。

## 开发执行记录（2026-08-04）

- P0-1～P0-8 的代码、配置、SQLite migration、测试、计划任务脚本、可观测性和运维文档已完成；功能开关保持默认关闭，外部 API schema 未修改。
- 本地候选只包含运行图事实；Planner 仅发布经 FlyAI 确定性关联且具备精确价格、可售席别和 allowlisted `jumpUrl` 的方案。
- 后端全量回归 290 passed；前端 helper 26 passed，TypeScript typecheck 与 Web/iOS/Android 构建通过；schema 重导出无差异。
- 真实低频 POC 已完成：2026-08-07 的 G1 发现与完整经停查询均返回 HTTP 200，dry-run 成功且未激活不完整批次。
- 首次 15 天建库已发起并验证 checkpoint/resume：受控续跑完成 103 个发现查询、保存 4959 个去重车次，下一任务键为 `D10`；随后 12306 返回访问控制，导入器按要求暂停，未绕过挑战。
- 当前阻塞：`logs/rail_timetable_import_checkpoint.json` 已保留可恢复进度，但 D0～D+14 尚未形成 15 个 ACTIVE 批次。待上游访问控制恢复后，使用同一 bootstrap 命令和 `--resume` 继续；因此“首次 15 天建库”这一运行验收项尚未完成，不能启用本地路由开关。
