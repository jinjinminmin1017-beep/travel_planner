# FlyAI CLI 强制退出竞态与来源熔断开发任务

来源：`docs/ARCHITECTURE.md`“FlyAI CLI 强制退出竞态与票务源熔断（2026-08-02，待实现）”。

状态：代码开发完成，目标环境在线发布门禁未通过（2026-08-03，提交 `2d632d7`、`526bbca`）。

## P0-1 CLI 成功退出生命周期

- 用现有 dump 结论向 FlyAI 上游提交缺陷：成功分支 `console.log(JSON)` 后执行 `process.exit(0)`，与 V8 WebAssembly background compile/Node platform shutdown 形成竞态。
- 首选升级到上游修复版本：成功 action 使用 `process.exitCode=0` 后返回，让 worker和事件循环自然排空；失败分支继续保持明确非零退出。
- 若必须临时补丁，只允许对固定 `@fly-ai/flyai-cli@1.0.16` 和官方包 SHA 做构建期精确补丁；目标片段、补丁前后 hash 任一不匹配即停止构建。
- 禁止运行期模糊改写 bundle、全局 monkeypatch `process.exit`、接受已崩溃进程 stdout 或逆向私有 HTTP。
- 扩展 `scripts/device-debug.ps1`：真实票务模式启动前执行 readiness probe；失败时停止启动并输出可行动诊断。只有显式 `-SkipFlyAI` 才允许无票务 UI 调试。

## P0-2 失败分类与熔断

- 在 `flyai_cli_client.py` 内部区分 fatal process exit、普通非零退出、业务 status、stderr、超时、限流和非法 JSON；对外保持现有稳定错误响应。
- 新增按 `source_id` 共享的 circuit state；确定性 fatal exit 首次出现后立即阻止同一 job 后续铁路、航班和混合查询。
- 跨 job 只使用短冷却和半开 probe；超时、限流不得套用 fatal exit 的阈值。
- 失败负缓存不得保存或重新解释 stdout；成功缓存和 single-flight 行为保持不变。
- Planner 收到唯一票务源熔断后直接形成真实失败覆盖，不调用旧航司、12306、browser worker 或模拟事实。

## P1 真实 Provider 状态

- 新增集中式 runtime health registry，记录真实成功/失败时间、脱敏失败分类、连续失败数、熔断状态和滚动延迟。
- 调整 `runtime_statuses()`：配置只决定 enabled/license，运行健康来自 registry；禁止把状态查询时间写成 `last_success_at`。
- `/api/health` 保持 liveness；`/api/data-sources/status` 和 admin status 在 FlyAI 熔断时返回 `DEGRADED`。
- 进程内实现即可，本期不新增数据库迁移或外部 API 字段。

## 验证

- 单元测试：成功 exit 0、fatal exit、stderr、超时、限流、非法 JSON、熔断打开/半开/恢复、并发 single-flight。
- 编排测试：首次 fatal exit 后，调用数不随候选路线组合增长；任务有界失败且 `plans=[]`。
- API 测试：真实失败更新 status，未成功过时 `last_success_at=null`，恢复后时间字段正确。
- 集成门禁：目标环境航班/铁路各 50 个获准样例全部 exit 0；记录 cold/warm P50/P95/P99。
- 回归：后端全量 pytest、schema export diff、前端 typecheck/build、敏感信息扫描。

## 完成定义

- 不再允许“可执行文件存在”被解释为 FlyAI 可运行，也不再把平台切换当作强制退出竞态的根因修复。
- 不忽略任何非零退出，也不采信崩溃进程的部分 stdout。
- 单次确定性崩溃不会放大为数十次 Provider 调用。
- 数据源状态与最近真实调用结果一致。

## 开发完成记录

- CLI 生命周期：官方仓库截至 2026-08-03 仍无高于 `1.0.16` 的版本；新增构建期精确补丁，只接受官方 bundle SHA `194a66eb...97da`，只修改航班/铁路成功 action，补丁后必须匹配 SHA `249791ae...1f58`。任一版本、目标片段或 hash 不一致均停止安装/启动。
- Windows 运行边界：认证 bundle 通过无 shell 参数数组由 Node `--single-threaded` 执行，消除 V8 background worker 与 libuv closing handle 的竞态；未认证 bundle 会在 Provider 构造阶段被拒绝。相对 executable 统一锚定项目根目录，后端从其他工作目录启动也不会误解析 shim。
- 启动门禁：`device-debug.ps1` 在真实票务模式启动前依次执行 bundle 校验和航班/铁路 readiness；`-SkipFlyAI` 会显式禁用票务源，只启动无票务 UI 调试模式。
- 失败分类与熔断：区分 fatal exit、普通非零退出、stderr、超时、限流、业务错误、非法 JSON/响应及体验模式；fatal 首次失败立即打开共享 source circuit，其他类别使用独立阈值、短冷却和单一半开 probe。
- 运行状态：新增进程内 runtime health registry，状态接口只展示真实成功/失败时间、稳定错误分类、连续失败、熔断状态和滚动平均延迟；应用 liveness 不受 Provider 降级影响。
- Planner/Provider：熔断错误通过现有航班、铁路 outcome 返回真实失败，不调用已退役航司、12306、browser worker 或模拟事实；缓存和 single-flight 成功语义保持不变。
- 数据库迁移：不需要。外部 API schema 保持 V1.18，schema export 无差异。

## 验证记录

- 定向测试：85 passed；覆盖 fatal/ordinary exit、stderr、timeout、invalid JSON、立即熔断、分类阈值、半开单 probe、恢复、真实状态字段、API liveness 和非根目录启动。
- 后端全量：`277 passed`。
- 前端：helper tests `26 passed`，TypeScript typecheck 通过，Web/iOS/Android Expo export 通过。
- 静态门禁：bundle patch hash 校验、secret 配置检查、Schema diff、Python/Node/PowerShell 语法、`git diff --check` 和真实 Key 泄漏扫描均通过。
- 真实 readiness：修复后航班 10 items / 1344ms，铁路 10 items / 1375ms，均完整 JSON、空 stderr、exit 0；完成 100 次门禁后再次启动时，上游普通 exit 1 被 readiness 正确阻止，未启动错误标记为可用的真实票务模式。
- 在线 50+50 门禁：100 次低频尝试中航班成功 24/50、铁路成功 23/50；16 次 `FLIGGY_NON_ZERO_EXIT`、1 次 `FLIGGY_BUSINESS_ERROR`，后续 36 次被短冷却熔断。未再出现 `3221226505` 或其他 fatal exit；成功样本 cold P50/P95/P99 为 1251.63/1458.92/2005.20ms，warm 为 0.65/0.78/1.13ms。
- 发布结论：代码开发完成，Windows fatal shutdown race 已消除且故障放大已阻断；由于上游普通 exit 1/业务失败导致 50+50 全成功率门禁未通过，真实票务生产发布继续阻塞，不得将本记录解释为在线验收通过。
