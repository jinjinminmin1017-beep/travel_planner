# 架构开发任务（2026-08-01）

## ARC-DEV-20260801-01 首次规划提交首帧误显未输入状态

来源：`docs/ARCHITECTURE.md`“首次提交到异步任务响应之间的启动态架构”。

完成状态：已完成。完成时间：2026-08-01 07:39:02 +08:00。代码提交：`a7c740e`。

### 问题与根因

- `startPlanning()` 在等待 `planTripAsync()` 前清空响应并切换到结果 tab。
- POST 尚未返回时 `authoritativeResponse=null`，现有状态机忽略本地 `OBSERVING` 并返回 `IDLE`。
- 结果页因此短暂显示“还没有规划结果 / 去云起填写”；用户现场看到的构建文案为“请输入目的地”。
- 后端初始响应包含真实 `travel_request`，不需要修改 API 或后端解析。

### 实现任务

1. 将本地规划生命周期收敛为 `IDLE | SUBMITTING | OBSERVING | PAUSED`；不要增加多个可互相矛盾的布尔值。
2. 在 `PlanningPageState` 增加 `SUBMITTING`，并在纯函数中实现以下优先级：
   - 无响应且有 blocking error -> `BLOCKING_ERROR`；
   - 无响应且 client phase 为 `SUBMITTING` -> `SUBMITTING`；
   - 无响应 -> `IDLE`；
   - 有响应 -> 保持现有活动态/暂停/终态推导。
3. `startPlanning()` 必须在切换到结果 tab 前同步设置 `SUBMITTING` 并保存本次提交的只读展示摘要。
4. `planTripAsync()` 返回活动 job 后切换为 `OBSERVING`；直接返回终态时切回 `IDLE`；catch 中结束提交态、保留原始输入并设置 blocking error。
5. 为 `SUBMITTING` 增加明确渲染分支。显示“正在理解你的行程”与受长度限制的原始输入摘要或“正在识别起点与终点”，不得显示未提交引导。
6. 不得为启动态伪造 `TravelPlanResponse`、`TravelRequest`、目的地或服务端进度；不要在客户端复制后端意图解析规则。
7. `loading` 继续只负责控件 busy/disabled，不得成为页面业务状态的唯一来源。
8. 保留 `planningRunId` 的旧请求隔离；保留旧结果的重规划不得被首次规划全屏启动态覆盖。

### 文件范围

- `frontend/src/App.tsx`
- `frontend/src/planning/planningState.ts`
- `frontend/src/components/planning/PlanningProgressScreen.tsx`，或新增同目录的启动态组件
- `frontend/tests/planningState.test.mjs`
- 必要的前端交互测试文件

明确不修改：

- `frontend/src/api/client.ts` 的外部请求合同
- `backend/`
- `schemas/`
- 数据库与持久化结构

### 验收标准

- 使用 deferred Promise 阻塞初始 POST 时，点击后的下一次渲染为 `SUBMITTING`，不出现 `IDLE`、`EMPTY`、`去云起` 或 `请输入目的地`。
- POST 返回 RUNNING job 后使用真实 `travel_request` 进入规划进度页。
- POST 返回终态时直接进入对应终态页面，不闪现未提交空态。
- POST 失败时显示阻断错误并保留输入，可编辑、可重试。
- 保留旧结果的重规划继续展示旧结果和局部 busy 状态。
- 较旧 run 的延迟响应不能覆盖当前 run。

### 验证命令

```powershell
cd frontend
npm run typecheck
npm run test:helpers
npm run build
```

### 风险与回滚

- 不要顺带重构导航、API、规划轮询或视觉系统。
- 修复可作为单独前端提交回滚；回滚视觉时仍需保留 `SUBMITTING` 状态语义。
- 仅修改文案、延迟 tab 切换或保留 `IDLE` 再加 loading 遮罩，不满足本任务。

### 完成记录

- 本地规划生命周期已扩展为互斥的 `IDLE | SUBMITTING | OBSERVING | PAUSED`，阻断错误优先于启动态。
- 首次 POST 返回前展示“正在理解你的行程”和最多 120 字的只读原始输入摘要，不伪造服务端请求、地点或进度。
- 活动 job 返回后进入 `OBSERVING`，直接终态和失败均退出提交态；POST 返回处增加 `planningRunId` 校验。
- 保留旧结果的重规划继续渲染旧结果与局部 busy，不进入首次规划全屏启动态。
- `npm run typecheck`、`npm run test:helpers`、`npm run build` 均通过。
