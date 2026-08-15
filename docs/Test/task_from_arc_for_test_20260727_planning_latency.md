# 架构测试任务（2026-07-27）

## ARC-TEST-20260727-01 规划链路延迟优化验证

来源：

- `docs/ARCHITECTURE.md`“规划链路延迟优化架构”
- `docs/Dev/task_from_arc_for_dev_20260727_planning_latency.md`

完成状态：待测试。

### 测试原则

- 性能结论必须来自计时和调用计数，不接受只检查代码结构。
- 冷缓存与暖缓存分开统计。
- 使用 fake Provider 做确定性测试，使用已批准真实 Provider 做受控 benchmark。
- 不在日志、fixture 或报告中写入 API key、cookie、token、完整用户输入。

### 单元测试：两阶段接驳

1. selected taxi 两端成功、其他 mode 延迟时：
   - 首个完整计划立即产生；
   - 不等待其他 mode；
   - 计划只有已验证选项；
   - 不出现规则估算。
2. selected mode 失败时：
   - 计划不得发布；
   - 后续允许按既有产品规则选择其他已验证方式时，必须显式切换 selected option。
3. alternatives 完成后：
   - `plan_id`、`segment_id`、selected option 稳定；
   - 新选项只包含各自验证事实；
   - 总价和总时长继续由 selected option 决定。
4. 取消或 generation 变化后，enrichment 不得覆盖终态。

### 单元测试：渐进协调器

1. 第一铁路计划形成时立即调用 progress sink，不等待第 4 个铁路计划。
2. 铁路和航班并发上报时，plans 集合与 progress 单调。
3. 未通过候选安全门禁的计划不得发布。
4. 同一 plan enrichment 只替换同 ID 内容，不生成重复计划。
5. 快照顺序在并发下保持确定性。

### 单元测试：地图调用计数

以 5 个唯一 OD 构造与真机样本同规模的 fixture：

1. driving 每个 OD 一次。
2. subway + bus 共用一次 transit 网络调用，但分别解析。
3. transit 响应只有公交时，不得生成地铁选项；反之亦然。
4. 机场接驳不调用 walking。
5. 直线距离超过 2200 米不调用 walking。
6. 短距离步行仍调用 Provider 并验证。
7. 不适用 walking 不写 source failure。
8. 总高德路线调用不超过 10 次。
9. 并发请求相同 key 时 single-flight 只发一个真实调用。

### 单元测试：地图优先级

1. 在 `QPS=1` fake limiter 下，首个候选的 selected mode 先于 alternatives。
2. 首个计划发布后，后排候选和 alternatives 最终仍完成，不得饥饿。
3. deadline 到达时，有首个完整计划则保留 `PARTIAL`；没有计划则按现有语义失败。
4. observe 模式只记录 would-timeout，不改变结果。

### 单元测试：航司挑战熔断

1. 第一个明确 challenge 后，当前 Provider 剩余 scope 调用数为 0。
2. challenge 记录为稳定 failure，不是 `EMPTY`。
3. 其他航司结果继续进入候选池。
4. 下一 job 可重新尝试，不得形成永久进程级禁用。
5. 关闭开关时恢复现有行为，便于回滚。

### 前端轮询测试

1. `RUNNING + plans=[]` 的相邻轮询间隔不超过 2 秒，包含可控抖动。
2. `RUNNING + plans非空` 后允许恢复较慢轮询。
3. fake timer 验证发布后客户端 P95 目标模型不超过 2 秒。
4. 后台暂停、前台恢复、继续获取、取消和重试状态不回归。
5. 网络失败不创建第二个 job，不进入 EmptyResults。

### 观测与安全测试

1. 每个成功、部分、失败和取消 job 都有结构化 summary。
2. summary 阶段耗时非负，`first_snapshot_ms <= final_result_ms`。
3. Provider 请求数与 fake 调用计数一致。
4. 日志中不得出现配置中的 API key 值、`key=` 明文、cookie、token 或完整 URL credential。
5. 日志不得包含完整地点输入；只允许哈希、长度或受控标识。
6. 30 秒配置漂移不得在 enforce 模式进入测试/部署默认值。

### 真实 benchmark

- 冷缓存至少 30 次，暖缓存至少 30 次。
- 至少覆盖：
  - 上海至北京铁路与航班并行；
  - 只有铁路；
  - 航司 challenge；
  - 地图单 mode 失败；
  - 无完整方案。
- 输出：
  - Intent、首计划、首快照、Recommendation、终态的 P50/P95/P99；
  - Provider family 耗时；
  - 高德 route/geocode 次数；
  - 航司 scope 次数；
  - route/location cache hit/miss；
  - 发布到客户端可见的附加耗时。

### 通过门槛

- 冷缓存服务端首个计划 P95 ≤ 12 秒。
- 冷缓存客户端首个计划可见 P95 ≤ 14 秒。
- 服务端最终结果 P95 ≤ 25 秒。
- 客户端发布感知附加耗时 P95 ≤ 2 秒。
- 复现样本高德路线调用 ≤ 10 次。
- 无规则估算、无未验证接驳、无 Provider QPS 提升。
- 外部 schema export 无 diff，版本保持 1.17。
- 现有后端、前端 helper、TypeScript 和导出测试全部通过。

### 建议执行

- `python -m pytest backend/app/tests`
- `npm run typecheck`（`frontend/`）
- `npm run test:helpers`（`frontend/`）
- `python scripts/export_schemas.py` 并检查 schema diff
- 新增 benchmark 命令必须将脱敏 summary 写入 `logs/`，不得写凭据。
