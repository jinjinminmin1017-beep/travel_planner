# 铁路导入优化验收

日期：2026-10-13；对应开发任务 `docs/Dev/task_from_arc_for_dev_20261013_rail_import.md`。

完成状态：已完成工程回归、本机迁移和单车真实接口验收；全国窗口实际容量仍需运行观测。

- [x] legacy v1 保留、按日期分片及 manifest 小体积。
- [x] 日期文件写完但 manifest 未落盘、首次迁移未落 manifest，两种崩溃后不回退。
- [x] SQLite 提交领先 checkpoint、虚假完成列表、进度节流和单实例锁。
- [x] 每日重新发现、同 generation 续跑、取消车次过滤、TTL 复核。
- [x] 撤回/隔离后清理旧 STAGING 行，完整性计数不永久卡住。
- [x] 近期与延期公平调度；确定性单日故障隔离、访问挑战全局停止。
- [x] 整轮预算包含 retry sleep；预算退出 flush、保留未完成状态。
- [x] 批量计数、幂等覆盖、删除/复制/写入事务回滚及 SQLite 句柄释放。
- [x] HTTP/等待/重试指标及剩余预算边界。
- [x] Windows 隐藏运行、日志、退出码传递及计划任务参数。
- [x] 全量后端 372 passed，PowerShell AST、Python compileall、diff whitespace 检查通过。
- [x] 真实 G1 单车 dry-run 通过，仅两次低频 HTTP 请求；无正式数据库写入。

证据：

- `rail_import_benchmark_20261013.json`：1000 车次、15 个历史日期、8 停站的离线 fixture；新进度实际写出约 3.75 MB、20 个 upsert 事务，旧全量逻辑写量预计约 6.54 GB。
- `rail_import_live_smoke_20261013.json`：2026-10-14 G1 的 DRY_RUN_COMPLETE 与实际请求/网络/等待指标。
- 本机 `logs/rail_checkpoint_migration_20261013.json`：72 个分日文件及旧 v1 SHA-256 保留验证。
- 本机 `logs/rail_refresh_*.json`：runner 的成功与非零退出码回执。

限制：离线 fixture 不代表实网吞吐；单车 smoke 不代表全国 15 天持续覆盖或外部接口 SLA。完整性、访问控制与实时票务核验均未放宽。
