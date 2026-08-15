# 架构开发任务（2026-07-27）

## ARC-DEV-20260727-01 规划链路延迟优化

来源：

- `docs/ARCHITECTURE.md`“规划链路延迟优化架构”
- `docs/Arc/time_performance.md`“2026-07-26 最后一次真机规划链路复盘”

完成状态：待开发。

### 现场基线

- 样本：`req_80b732447702 / job_f9de40d1d515`
- 提交至服务端终态：39.928 秒。
- 服务端 job：35.728 秒。
- 首个渐进快照：job 后约 30 秒；客户端首次看到计划约为提交后 37.8 秒。
- 外部调用：20 次高德路线、1 次高德地理编码；高德路线 `QPS=1`。
- 5 个唯一 OD 产生 5 driving、10 transit、5 walking 请求。

### P0-1 结构化阶段观测

1. 为单 job 记录：
   - intent parse
   - rail/flight core facts
   - first plan built
   - first snapshot
   - selected transfer hydration
   - alternative transfer hydration
   - candidate finalize
   - recommendation
   - final result
2. 记录 Provider 请求数、挑战/失败数、route/location cache hit/miss。
3. job 结束输出一条脱敏 JSON summary，必须包含 request/job/trace 标识。
4. 不记录完整输入、地点原文、API key、token、cookie 或票务会话。
5. 对 `httpx` URL 日志增加 credential 脱敏或关闭 INFO 完整 URL；修复后提醒运维轮换旧日志中暴露的凭据。

### P0-2 两阶段接驳

1. 将 `build_local_transfer_segment()` 的职责拆为：
   - 验证 selected mode 并创建最小完整接驳；
   - 补齐其他真实备选 mode。
2. selected mode 未验证成功时不得创建计划，不得回退规则估算。
3. selected mode 成功后即可形成完整门到门计划；备选 mode 不得阻塞首个计划。
4. 补齐备选后复用稳定 `segment_id`、`option_id`、`plan_id`。
5. 当前选择仍存在时，渐进快照更新不得改变选中项。
6. 用功能开关控制两阶段行为，关闭时恢复当前一次性构建。

### P0-3 单计划渐进发布

1. 增加线程安全候选进度协调器，铁路/航班 builder 每形成一个完整计划即上报。
2. 协调器复用 `generate_candidate_plan_pool()` 和最终安全门禁。
3. 只有完整、真实、可推荐计划才能发布。
4. 快照 plans 集合、progress、updated_at 单调；取消/generation 写保护继续生效。
5. 不等待 Provider family future 整体完成才发布首个计划。
6. 同一 `plan_id` 的后续 enrichment 允许替换内容，但不得发布半成品 segment。

### P1-1 地图请求减半

1. 对高德综合公交建立 query-family 层的 single-flight：
   - key：Provider + OD + city + environment + transit family；
   - 地铁和公交共享一次网络响应；
   - 两种 mode 分别解析和校验。
2. walking 请求前安全短路：
   - 机场接驳直接不适用；
   - 经纬度直线距离超过 2200 米直接不适用。
3. 短路不得产生 `SourceFailure` 或 `missing_components`。
4. 规划内现有 route/location single-flight 继续保留。
5. 地图任务优先级：
   - 首个候选 selected mode；
   - 其他候选 selected mode；
   - alternatives。
6. 不提高 Provider QPS，不引入无界线程池。

### P1-2 航司挑战熔断

1. 青岛航空返回明确验证挑战后，当前 job 停止该 Provider 剩余 query scope。
2. 记录稳定 error code 和 source failure，不标记为 `EMPTY`。
3. 其他航司继续执行；不得扩大为全局永久禁用。
4. 以独立开关控制 job 级挑战熔断。

### P1-3 前端轮询感知

1. `plans=[]` 且服务端活动时，轮询退避上限为 2 秒并保留抖动。
2. 首个计划出现后恢复现有较低频率。
3. App 后台暂停、前台恢复、观察窗口和同 job 恢复语义不变。
4. 不新增重复 job，不把轮询失败解释为服务端终态。

### 配置要求

- 当前本地 `.env` 的 job timeout 为 30 秒，与默认 180 秒不一致。
- 本任务不得开启强制 30 秒 deadline。
- benchmark 完成前保持 `TRAVEL_ASYNC_JOB_DEADLINE_MODE=observe`，部署配置恢复单一 180 秒口径。
- 每个优化开关写入 `.env.example` 和架构文档。

### 文件范围

- `backend/app/services/local_transfer_engine.py`
- `backend/app/services/planner.py`
- `backend/app/services/planning_progress.py`
- `backend/app/data_sources/map_providers.py`
- `backend/app/data_sources/flight_providers.py`
- `backend/app/services/observability.py`
- `backend/app/main.py`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx` 或现有 planning helper
- 对应测试、`.env.example` 和文档

### 禁止事项

- 不恢复规则估算。
- 不减少来源真实性或安全门禁。
- 不通过提高 Provider QPS 伪造性能收益。
- 不把同一 transit 响应未经 mode 校验直接复制成地铁和公交。
- 不为了首屏速度减少最终已批准 Provider 或隐藏 source failure。
- 不修改外部 V1.17 schema；若确需修改，先回到架构任务更新 API contract。

### 交付顺序

1. 提交 A：结构化阶段观测、HTTP URL 脱敏、配置一致性。
2. 提交 B：两阶段接驳与单计划渐进发布。
3. 提交 C：transit 合并、walking 短路和地图优先级。
4. 提交 D：航司挑战熔断。
5. 提交 E：前端活动空态 2 秒轮询上限。
6. 每个提交必须可独立回滚，不得合成一次大改。

### 验收目标

- 冷缓存服务端首个计划 P95 ≤ 12 秒。
- 冷缓存客户端首个计划可见 P95 ≤ 14 秒。
- 服务端最终结果 P95 ≤ 25 秒。
- 发布到客户端感知附加耗时 P95 ≤ 2 秒。
- 复现样本高德路线网络调用 ≤ 10 次。
- 最终仍可得到与数据源事实相符的 4 个铁路、2 个航班方案；若实时数据变化导致数量不同，必须用 Provider 事实解释。
- 外部 schema version 保持 1.17。
