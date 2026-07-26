# 架构开发任务（2026-07-26）

## ARC-DEV-20260726-01 异步规划假空态与渐进结果

来源：`docs/ARCHITECTURE.md`“异步规划假空态与渐进结果架构”。

完成状态：已完成（2026-07-26）；P0、P1、P2 与期限观测/强制模式均按可回滚提交交付。

### 现场基线

- 请求 `req_7e9e98fb9995` 的客户端轮询窗口约 120 秒，最后一次 GET 为 08:02:52。
- 后端 08:03:12 才完成，最终为 `COMPLETE`、6 个计划且推荐有效。
- 当前前端将最后保留的 `RUNNING + plans=[]` 响应渲染成“暂无可用方案”。
- 本次运行共发生 69 次外部请求，其中高德 50 次；第一个铁路方案 08:01:10 已在 Planner 内生成，但异步 job 直到最终完成才发布 plans。

### 历史归因与回归锚点

- `067b127`（2026-06-27，`sync from windows`）引入异步规划、`MAX_POLL_ATTEMPTS=100`、`POLL_INTERVAL_MS=1200` 和仅按 `plans.length` 落普通空态的基础逻辑；同时声明的服务端 job timeout 未接入执行链路。
- `b6c9a9b`（2026-07-11，`Complete route planning UI flow`）为保留已有结果，将全局错误分支改为 `error && !response`。这使 `RUNNING + plans=[]` 在观察窗口耗尽后绕过 ErrorState，直接落入 `EmptyResults`，是当前可见假空态的直接回归点。
- `7603cf3` 之后的真实地图接驳，以及 `1e4413f`、`c894873`、`03c8232` 引入的多航司/机场范围查询扩大了串行 I/O，令旧的 120 秒假设稳定失效。
- 修复不得回退真实数据门禁，也不得通过恢复规则估算、关闭已批准 Provider 或隐藏失败来缩短耗时。

### P0 前端状态机

1. 从 `frontend/src/App.tsx` 抽出纯函数状态推导模块，输入至少包含 `planning_status`、`async_job.job_status`、`plans.length`、本地 observation 状态和 error 类型，输出唯一页面状态。
2. 不得继续使用 `error && !response` 或 `plans.length === 0` 作为独立业务判定。必须保留两种原始产品意图：
   - 终态已有可用 plans，局部重试失败：继续展示旧结果和非阻断 error panel；
   - 活动态空 plans，观察窗口耗尽：展示仍在规划，不得展示旧结果空态。
3. 为本地轮询增加 `OBSERVATION_PAUSED` UI 状态。观察窗口耗尽时保留 job 与响应，不调用普通空态，不改写服务端 `planning_status`，不清除可用于恢复的 `polling_url`。
4. App 回到前台或用户点击“继续获取”时，先 GET 原 `polling_url`；任务仍活动才继续轮询，禁止创建重复 job。
5. 将固定次数循环改为 elapsed-time 观察窗口和有上限退避；配置只影响观察体验，不参与业务终态判断。禁止把 `MAX_POLL_ATTEMPTS` 从 100 调大作为本任务的修复。
6. 拆分页面分支：
   - `RUNNING + plans=[]`：全屏规划进度；
   - `RUNNING + plans非空`：结果加局部 loading；
   - observation paused：仍在规划与继续获取/取消；
   - `NO_MATCH`：约束无匹配；
   - `FAILED`：失败与重试；
   - `COMPLETE/PARTIAL + plans非空`：正常结果。
7. 当前选中计划仍存在时保持选中；渐进或最终快照移除当前计划时再选择稳定排序后的首个计划。
8. P0 不修改外部 API schema，不要求等待后端渐进快照上线；应能独立发布并立即消除假空态。

### P1 后端渐进快照

1. 定义不依赖 HTTP、SQLite 或全局 store 的 `PlanningProgressSink` 协议；同步规划注入 no-op，异步规划注入 job snapshot writer。
2. 当完整门到门计划通过与最终候选池一致的安全/可推荐性门禁后，发布 `RUNNING` 渐进快照。
3. 渐进快照可包含 `plans`，但 `recommendation_result=null`；不得发布骨架、占位价格、规则估算接驳或未通过门禁的计划。
4. `progress` 与 `async_job.updated_at` 单调更新；写入前验证 job 未取消且 generation 与当前任务一致。
5. 完整规划结束后仍执行统一候选筛选和推荐，并用 `COMPLETE/PARTIAL/NO_MATCH/FAILED` 覆盖为终态。
6. 以功能开关控制渐进发布；关闭时保留当前只写最终快照行为。

### P1 服务端期限

1. 处理当前未被使用的 `TRAVEL_ASYNC_JOB_TIMEOUT_SECONDS`：接入统一 deadline，或删除并替换为语义明确的新配置，禁止无效配置继续存在。
2. 使用单调时钟计算 deadline，将剩余预算传给 Provider 家族和接驳扩展；开始新分支前检查剩余预算。
3. deadline 到达且已有完整方案时返回 `PARTIAL`；没有完整方案时返回可解释 `FAILED`。终态必须由服务端保存。
4. 先增加观测模式，记录 would-timeout，不中止任务；根据真实 P95/P99 校准后再灰度强制。不得直接采用当前 30 秒默认值。

### P2 延迟与观测

1. 增加 `first_usable_plan_latency_ms`、`final_result_latency_ms`、渐进快照次数和 deadline 结果指标。
2. 以规范化 `起点坐标 + 终点坐标 + mode + Provider` 为规划内路线键，复用同一任务的地点解析与路线查询；相同键最多触发一次真实外部请求。
3. 铁路与航班 Provider 家族只在共享 QPS、缓存、熔断和总 deadline 约束下做有界并行。
4. 日志只记录 job/request 标识、阶段、计数和耗时，不记录完整用户输入、API key 或票务会话材料。

### 交付顺序

1. PR/提交 A：先增加前端纯状态机与确定性测试，再替换 `App.tsx` 分支；不得夹带视觉重构。
2. PR/提交 B：增加 `PlanningProgressSink`、generation 写保护与渐进快照测试。
3. PR/提交 C：加入规划内路线复用和延迟指标。
4. PR/提交 D：deadline 先观测、后单独灰度强制；不得和 P0 合并为一次不可拆回滚的大提交。

### 文件范围

- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/planning/planningState.ts`（建议新增）
- `backend/app/main.py`
- `backend/app/services/planner.py`
- `backend/app/services/task_queue.py`
- `backend/app/services/store.py`
- `backend/app/services/candidate_generator.py`
- `backend/app/services/constraints/`
- `backend/app/services/observability.py`
- 对应前后端测试

### 验收标准

- 使用假时钟模拟服务端在客户端初始观察窗口之后完成时，UI 不出现“暂无可用方案”，继续获取后能展示最终计划。
- 精确复现 `b6c9a9b` 场景：`error` 非空、response 存在但为 `RUNNING + plans=[]` 时，不进入 `EmptyResults`；response 为终态且 plans 非空时，仍保留旧结果与 error panel。
- 活动态空 plans、活动态非空 plans、NO_MATCH、FAILED、PARTIAL、COMPLETE 六类状态互不串页。
- 第一个完整安全计划产生后，无需等待所有交通方式与 LLM 推荐即可在后续 GET 中看到。
- 取消/重试后旧后台任务不能覆盖新任务或取消终态。
- deadline 观测模式不改变结果；强制模式有方案时保留 `PARTIAL`，无方案时返回可解释 `FAILED`。
- 相同规划内重复的地图路线键只发起一次 Provider 请求；不得再次出现“计划数 × 两端接驳 × 四种方式”的无缓存重复扇出。
- 外部 schema version 保持 `1.17`，schema export 无非预期 diff。

### 风险与回滚

- P0 必须先于或与 P1 同时发布。
- 渐进发布与强制 deadline 使用独立开关；出现问题可分别关闭。
- 回滚不得恢复通过 `plans.length === 0` 判断活动任务为空结果的逻辑。
- 仅增加轮询次数、仅改错误文案或仅隐藏 EmptyResults 均不满足验收。

## 开发完成记录

- P0 前端状态机与观察暂停：提交 `92d7e08`。
  - 新增纯状态推导、elapsed-time 观察窗口、有上限退避和抖动。
  - 观察暂停保留原 job 与 `polling_url`；继续获取和前台恢复先 GET 同一任务。
  - 活动态空计划、活动态有计划、NO_MATCH、FAILED、PARTIAL、COMPLETE 不再串页。
- P1 渐进快照与 generation 写保护：提交 `e2043c9`。
  - Planner 通过领域 `PlanningProgressSink` 发布已通过正式候选安全门禁的完整方案。
  - 渐进快照保持 `RUNNING`、`recommendation_result=null`、进度单调。
  - 取消提升 generation；旧 worker 不能覆盖取消、重试或已有终态。
- P2 路线复用、Provider 家族有界并行与延迟指标：提交 `0e66dd2`。
  - 相同规划内规范化路线键最多触发一次真实地图请求；地点解析同步复用。
  - 铁路与航班直达族最多 2 worker 并行，继续服从原 Provider QPS、缓存和熔断。
  - 指标覆盖 `first_usable_plan_latency_ms`、`final_result_latency_ms`、渐进快照数和缓存命中。
- 服务端期限：提交 `17c3748`。
  - `TRAVEL_ASYNC_JOB_TIMEOUT_SECONDS` 已接入单调时钟 deadline，默认 180 秒。
  - 默认 `TRAVEL_ASYNC_JOB_DEADLINE_MODE=observe`，只记录 `WOULD_TIMEOUT`。
  - 显式强制模式到期时，有完整方案返回 `PARTIAL`，无完整方案返回可解释 `FAILED`。
- 数据库迁移：不需要。
- 外部 API：继续使用 V1.17 现有字段，无 schema diff。
- 验证：
  - 后端全量 `246 passed`。
  - 前端 TypeScript 通过，helper/UI 合同 `19 passed`。
  - Expo Web、iOS、Android 导出通过。
  - Python compileall 通过；schema export 无差异。
