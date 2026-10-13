# Railway Timetable Operations

更新日期：2026-10-13

## 安全边界

- 本地快照只保存 G/D/C 运行图和完整经停，不保存余票、价格、席别、账号、Cookie 或跳转 URL。
- 导入器单线程运行，默认请求间隔 1.5 秒。HTTP 429、验证码、安全挑战或访问限制会立即暂停并保存 checkpoint。
- 不使用历史 `train_list.js`。车次发现使用当前日期的 12306 train search，完整经停使用 `queryTrainInfo`。
- 本地候选必须经 FlyAI 实时核票，只有价格、席别和 allowlisted `jumpUrl` 完整的候选才能进入 API。

## 配置

默认全部关闭：

```env
TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED=false
TRAVEL_RAIL_LOCAL_ROUTING_ENABLED=false
TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED=false
TRAVEL_RAIL_TIMETABLE_HORIZON_DAYS=15
TRAVEL_RAIL_TIMETABLE_REFRESH_AT=03:30
TRAVEL_RAIL_TIMETABLE_RETENTION_DAYS=45
TRAVEL_RAIL_TIMETABLE_FRESHNESS_HOURS=36
TRAVEL_RAIL_TIMETABLE_IMPORT_INTERVAL_SECONDS=1.5
```

非 dry-run 导入要求先开启 `TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED`。完成 bootstrap、完整性检查和 FlyAI 集成验证后，再开启 `LOCAL_ROUTING_ENABLED`。仅开启本地路由但未开启快照会在启动配置解析阶段失败。

## 首次建库

先执行低频 dry-run：

```powershell
.\.venv\Scripts\python scripts\import_12306_timetable.py --date-from 2026-08-07 --days 1 --train-number G1 --dry-run
```

再执行 D0～D+14 bootstrap：

```powershell
.\.venv\Scripts\python scripts\import_12306_timetable.py --mode bootstrap --days 15 --resume --auto-resume-transient
```

导入过程按服务日创建 STAGING 批次。只有车次发现完成、所有服务至少有两个合法经停、站序连续且到发时间完整时，才会在单个 SQLite 事务中切换为 ACTIVE。失败或中断不会替换上一 ACTIVE 批次。

默认 checkpoint 参数仍为 `logs/rail_timetable_import_checkpoint.json`。新版读取旧 v1 文件后，写入 `logs/rail_timetable_import_checkpoint.v2.json` 小 manifest 和 `logs/rail_timetable_import_checkpoint.v2.d/<服务日>.json` 分日文件，保留旧文件供回滚。恢复时重复执行同一命令并保留 `--resume`；已提交车次以 SQLite 为准，进度文件落后不会丢失已提交的服务。

进度按车次数/时间间隔保存，激活、暂停、失败和预算退出时强制保存；发现进度仅写当前服务日，不再每完成一车重写所有历史日期。手工与计划入口共享操作系统文件锁，第二个使用同一 checkpoint 的进程会退出，防止同时覆盖文件。

## 每日刷新

手工刷新：

```powershell
.\.venv\Scripts\python scripts\import_12306_timetable.py --mode refresh --days 15 --resume --max-run-seconds 28800 --detail-ttl-hours 36
```

Windows Task Scheduler：

```powershell
.\scripts\install_rail_timetable_refresh.ps1 -Mode Install -RefreshAt 03:30 -MaxRunSeconds 28800 -DetailTtlHours 36
.\scripts\install_rail_timetable_refresh.ps1 -Mode Check
.\scripts\install_rail_timetable_refresh.ps1 -Mode Uninstall
```

计划任务使用受控的 scheduled 入口；`TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED=false` 时会安全退出且不访问网络。手工 dry-run 不受刷新开关限制。

刷新调度优先处理近期缺失/过期的服务日，并保留远期扩展与被推迟日期的工作机会。普通单日数据/完整性错误会记录该日失败后继续其他日期；访问控制仍全局停止，数据库和文件系统错误也不会被当作可忽略的单日错误。

新的每日 refresh 使用北京时间日期作为 generation，重新发现该服务日的车次；同 generation 的临时重试与 `--resume` 继续已有发现进度。摘要包括来源实际返回的始发/终到时刻及跨日字段；没有超过 `--detail-ttl-hours` 且摘要一致的详情才可复用，保留原始 `fetched_at`。详情到期必须重新获取，不能以车次身份不变推断中间停站和时刻不变。

`--max-run-seconds` 限制整个监督进程（包括自动续跑等待），`--max-date-seconds` 可另设单日预算；手工命令不传预算时沿用无限预算。预算到期是可恢复的未完成状态，保留 STAGING，不能标记 COMPLETE 或 ACTIVE。单次请求也会缩短至剩余预算，检查点和事务完成后才退出。

计划任务默认启用受控自动续跑：

- 只有连接中断、读取超时和 HTTP 5xx 等 `RAIL_TIMETABLE_TRANSIENT_FAILURE` 会触发进程级 resume。
- 单次任务最多自动 resume 6 次，默认等待 5、10、20、40、60、60 分钟；每次都复用 checkpoint，不重复已完成车次。
- HTTP 429、验证码、401/403/418 或非 JSON 安全挑战返回退出码 2 并立即停止，不进入自动续跑。
- 确定性解析/完整性错误在该日期记录失败，继续窗口内其他日期；不会在同一坏车次上无限自动重试。数据库/文件系统系统性错误停止整轮。
- Windows 任务设置为 `MultipleInstances=IgnoreNew`，已有导入实例运行时不会启动第二个实例。
- Windows 任务明确允许使用电池启动，且切换到电池供电时不会终止正在写 checkpoint 的导入；超时和访问控制规则保持不变。
- Windows 任务不设置运行时长强制终止；默认由 importer 自己执行 8 小时整轮预算并安全保存断点。下一次触发由 `IgnoreNew` 防重复；不要用任务计划程序强杀替代程序内预算。
- 任务通过隐藏的 `scripts/run_rail_timetable_refresh.ps1` 运行 Python，保存 `logs/rail_refresh_<时间>_<进程>.stdout.log`、`.stderr.log` 和 `.json` 退出回执。日志含阶段耗时、请求/复用数与检查点写出量，不含票务账号或凭据。
- 本机任务仍使用交互用户身份，需要该 Windows 用户已登录；锁屏不等于退出登录。若部署到长期服务器，应采用具备合适身份的等价任务服务。

Linux cron 等价配置示例：

```cron
30 3 * * * cd /opt/travel_planner && ./.venv/bin/python scripts/import_12306_timetable.py --mode refresh --days 15 --resume --scheduled --auto-resume-transient --max-run-seconds 28800 --detail-ttl-hours 36 >> logs/rail_refresh.stdout.log 2>> logs/rail_refresh.stderr.log
```

systemd timer 应调用同一 refresh 命令并设置 `Persistent=true`，以便停机后 catch-up。导入不得在 FastAPI 请求或 lifespan 中启动。

## 离线容量验证

```powershell
.\.venv\Scripts\python scripts\benchmark_rail_timetable_import.py --output logs\rail_import_benchmark.json
```

基准在临时数据库与合成时刻表上验证写入成本，不访问 12306，不读取真实 SQLite 或 checkpoint。报告中的本地吞吐不能作为外部来源的成功率或全国 15 天覆盖承诺；真实运行需结合阶段耗时、日期覆盖、新鲜度与失败原因判断容量。

## 回滚

停止当前任务后切回旧代码，可使用保留的 v1 checkpoint 和原 SQLite；数据库表结构及 API 契约没有变化。新版实际进度优先保存在 SQLite，因此回滚后的旧 importer 可能重复处理部分已经提交的车次；唯一键保证 upsert 幂等。不要在新旧两个进程同时运行时回滚。

## 状态判断

导入退出码与结果状态：

| 退出码 | 含义 |
| --- | --- |
| 0 | 本轮 COMPLETE / DRY_RUN_COMPLETE，或 scheduled 开关关闭的 DISABLED；以 stdout 状态区分 |
| 1 | PARTIAL_FAILED，存在确定性日期失败；或 SYSTEM_FAILED，文件/数据库错误停止 |
| 2 | PAUSED，访问控制全局停止 |
| 3 | 临时传输失败，未启用监督或受控重试耗尽 |
| 4 | BUDGET_EXHAUSTED，已保存可恢复进度，部分日期尚未完成 |
| 5 | ALREADY_RUNNING，同一 checkpoint 已被另一导入进程持有 |
| 130 | 人工中断；重新执行带 `--resume` 的命令恢复 |

任务计划程序的非零结果不等于数据全部丢失；先读取相应 stdout、stderr 和退出回执，再检查服务日 ACTIVE/STAGING 覆盖。

`GET /api/observability/metrics` 返回：

- `rail_timetable_coverage`：日期、批次状态、新鲜度、服务数和停站数。
- `rail_runtime.local_search_latency_ms`：本地搜索 P50/P95/P99。
- `rail_runtime.inventory_verification_latency_ms`：核票耗时分位数。
- `rail_runtime_counters`：候选数、核票组数、外部调用数和预算耗尽次数。

语义区分：

- `rail_local_no_schedule`：存在新鲜 ACTIVE 快照，但站点范围内没有直达或一次换乘。
- 快照不可用：目标日期没有新鲜 ACTIVE 批次；Planner 回退现有实时发现路径。
- `RAIL_INVENTORY_EMPTY`：FlyAI 成功查询但没有返回目标候选，可视为无票。
- `RAIL_INVENTORY_NOT_ON_SALE`：Provider 明确表达未开售。
- `RAIL_INVENTORY_PROVIDER_UNAVAILABLE`：超时、限流、熔断或响应无效；不得表达为无车或无票。

## 回滚

1. 设置 `TRAVEL_RAIL_LOCAL_ROUTING_ENABLED=false`，立即恢复原实时路线发现路径。
2. 如需停止导入，再设置 `TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED=false` 并卸载调度任务。
3. 保留新增表和历史批次；回滚不删除快照、不改写历史计划。
