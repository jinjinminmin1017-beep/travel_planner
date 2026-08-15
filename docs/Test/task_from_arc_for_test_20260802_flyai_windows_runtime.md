# FlyAI CLI 强制退出竞态与熔断测试任务

来源：`docs/ARCHITECTURE.md`“FlyAI CLI 强制退出竞态与票务源熔断（2026-08-02，待实现）”。

状态：待测试。

## 1. CLI 退出生命周期与门禁

- 固定记录 OS、架构、Node、libuv、CLI 版本及 CLI 包 hash。
- 静态/构建门禁验证航班、铁路成功分支不再在输出后直接调用 `process.exit(0)`。
- 同一无 Key 最小复现必须完整输出、stderr 为空、exit 0；ProcDump 不再捕获 `0xC0000409`，不得出现 `DelayedTaskScheduler::PostDelayedTask -> uv_async_send` closing-handle 断言。
- readiness probe 只有在完整 JSON、stderr 为空、exit 0 时通过。
- stdout 为完整成功 JSON但 exit 非0时必须失败；不得生成 offer、价格或 redirect。
- `-SkipFlyAI` 只进入明确的无票务调试模式，UI/API 不得把 FlyAI 标为 OK。

## 2. 熔断与调用上限

- 构造与 `3221226505` 等价的 fatal exit fixture；首次失败后同一 job 的铁路、航班和混合分支不得再次执行 runner。
- 多线程并发首调只允许 single-flight 领导者启动 CLI，等待者复用同一类型失败。
- 验证短冷却、半开单探针、成功关闭熔断和失败重新打开。
- 有效空、业务失败、限流、超时、非法响应与 fatal exit 分别测试，不得错误共用立即熔断策略。
- 无验证事实时终态为 `FAILED`、`plans=[]`，不触发旧来源 fallback。

## 3. 状态与可观测性

- 启用但从未调用的来源不得伪造 `last_success_at`。
- fatal exit 后 `health_status=DEGRADED`、`last_failure_at` 为真实时间、`latest_failure` 为脱敏稳定分类。
- 半开恢复成功后状态回到 OK，保留可解释的最近成功时间。
- `/api/health` 在 Provider 降级时仍可表示应用存活；数据源状态承担依赖健康语义。
- 日志、API、SQLite、fixture 和进程参数不得出现 API Key、原始 stdout 或完整 jumpUrl。

## 4. 真实门禁

- 在候选目标组合完成航班与铁路各 50 个获准低频样例。
- 所有成功样例必须 exit 0；统计成功率、错误分类、cold/warm P50/P95/P99。
- 当前未修复的 Windows 10 + Node 24.14.0 + CLI 1.0.16 基线必须稳定复现 dump 中的强制退出竞态；修复版本必须在同一环境通过，不能用更换平台掩盖问题。

## 5. 回归

- 后端全量 pytest。
- Schema export 无差异。
- 前端 typecheck、helper tests 与 build 通过。
- Provider 配置检查、公开 smoke 与敏感信息扫描通过。
