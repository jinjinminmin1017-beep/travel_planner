# Railway Timetable Operations

更新日期：2026-08-04

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
.\.venv\Scripts\python scripts\import_12306_timetable.py --mode bootstrap --days 15 --resume
```

导入过程按服务日创建 STAGING 批次。只有车次发现完成、所有服务至少有两个合法经停、站序连续且到发时间完整时，才会在单个 SQLite 事务中切换为 ACTIVE。失败或中断不会替换上一 ACTIVE 批次。

默认 checkpoint：`logs/rail_timetable_import_checkpoint.json`。恢复时重复执行同一命令并保留 `--resume`；已完成的稳定任务键会跳过，服务写入使用唯一键 upsert。

## 每日刷新

手工刷新：

```powershell
.\.venv\Scripts\python scripts\import_12306_timetable.py --mode refresh --days 15 --resume
```

Windows Task Scheduler：

```powershell
.\scripts\install_rail_timetable_refresh.ps1 -Mode Install -RefreshAt 03:30
.\scripts\install_rail_timetable_refresh.ps1 -Mode Check
.\scripts\install_rail_timetable_refresh.ps1 -Mode Uninstall
```

计划任务使用受控的 scheduled 入口；`TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED=false` 时会安全退出且不访问网络。手工 dry-run 不受刷新开关限制。

Linux cron 等价配置示例：

```cron
30 3 * * * cd /opt/travel_planner && ./.venv/bin/python scripts/import_12306_timetable.py --mode refresh --days 15 --resume --scheduled
```

systemd timer 应调用同一 refresh 命令并设置 `Persistent=true`，以便停机后 catch-up。导入不得在 FastAPI 请求或 lifespan 中启动。

## 状态判断

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
