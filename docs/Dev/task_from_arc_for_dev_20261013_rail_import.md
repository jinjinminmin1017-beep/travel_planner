# 铁路导入吞吐、刷新与恢复优化

来源：用户于 2026-10-13 确认完成导入优化；架构依据为 `docs/ARCHITECTURE.md` 10.10。

完成状态：已完成代码、测试、本机 checkpoint 迁移及计划任务部署。

## 范围

仅优化离线时刻表获取与恢复，不修改前端、在线票务契约、SQLite 表结构或来源访问频率。保留完整性检查、STAGING/ACTIVE 原子边界和访问控制停止规则。

## 完成任务

- [x] IMP-01：v2 小 manifest 与分服务日 checkpoint，旧 v1 保留式迁移；原子保存及跨进程锁。
- [x] IMP-02：以 SQLite 已提交服务恢复断点，批量落库、节流保存；预算或中断前保存已成功获取的服务。
- [x] IMP-03：upsert 事务内准确增量计数、批量复制；激活仍核实实际数据；事务上下文立即关闭 SQLite 句柄。
- [x] IMP-04：近期缺失/过期优先，保留远期与延期日期工作；普通日期失败隔离，访问控制和系统存储故障全局停止。
- [x] IMP-05：新每日 generation 重发现，同 generation 续跑；时刻字段参与指纹，36 小时详情 TTL；明确撤回/隔离的旧 STAGING 行同步删除。
- [x] IMP-06：整个监督进程共享时间预算，含退避等待及请求边界；输出阶段耗时、实际请求数、复用数、checkpoint 字节与次数。
- [x] IMP-07：隐藏 Windows runner、持久 stdout/stderr/退出回执；恢复每日 03:30 任务，默认 8 小时程序内预算。
- [x] IMP-08：恢复/错误/预算/计数专项回归、离线容量脚本、单车低频真实 dry-run、全量后端测试及运维文档同步。

## 验证结果

- 全量后端：372 passed，45.90 秒；测试使用临时 SQLite，不触碰正式数据库。
- 专项：pipeline 21、store 19、provider 23、benchmark 2，合计新增 65 项；原铁路 30 项保持通过。
- PowerShell AST、Python compileall、`git diff --check` 通过。
- Windows runner 的 DISABLED 路径返回 0；snapshot 未启用路径的 Python 退出码 2 正确传递，并有 stderr 和退出回执。
- 实际低频 POC：2026-10-14 G1，2 个 HTTP 请求，DRY_RUN_COMPLETE、无重试、stderr 为空；未写正式数据库。
- 容量证据：`docs/Test/rail_import_benchmark_20261013.json`；1000 个合成服务下旧逻辑预计写出 6,539,280,000 bytes，新周期分日实际写出 3,754,496 bytes，20 个 upsert 事务且无 upsert COUNT。

## 本机部署

- 旧 checkpoint 260,476,081 bytes 保留，迁移前后 SHA-256 一致。
- 72 个服务日已拆分，manifest 为 12,744 bytes；最新服务日 10/27 仍为 STAGING，迁移不冒充完成数据。
- `TravelPlannerRailTimetableRefresh` 已安装且待命，下次 2026-10-14 03:30（北京时间），交互用户登录身份。
- 本次没有启动全国窗口导入；实际覆盖和新鲜度需要后续任务运行验证。

## 回滚

停止导入进程后切回旧代码及保留的 v1 checkpoint；SQLite 表结构未变化。旧代码可能幂等重写新版已经提交的部分车次，不能同时运行新旧入口。
