## 2026-07-11 08:34:23 +08:00

- 任务：完成路径规划前端落地 Phase 1–6 与全部代码验收项。
- 代码提交：`b6c9a9b90300cb8b82c513600b81564cf8a76f5d`。
- 修改内容：
  - 将规划进度、方案总览、方案选择、推荐理由、路线时间轴、固定操作栏、路线详情和分段调整拆分为独立组件。
  - 规划中页面接入真实起终点、四阶段状态、地图汇聚动画、取消任务和 reduced-motion 降级。
  - 总览使用真实方案计算价格、耗时、换乘与差异；部分结果和数据失败保持可访问。
  - 详情页保留收藏、分享、复制、外部官方跳转、座席/舱位/接驳重算和反馈；风险保持方案级展示。
  - 重新规划与来源重试保留上一版结果并显示局部骨架，不再清空整个页面。
  - 触控目标统一为 48px，补齐 Web 运行依赖和横竖屏配置。
  - 增加 UI 合同测试和 360/390/430px 视觉回归截图。
- 验证：
  - `npm run test:helpers`：通过，8 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，iOS / Android / Web 导出成功。
  - `npx expo export --platform web`：通过。
  - Web 360×800、390×844、430×932：无横向溢出；1024px 内容区按 720px 上限居中。
  - 真实界面验证：规划中、无方案、部分结果、方案切换、时间调整、详情、分段展开/禁用、来源页返回与方案保持均通过。

## 2026-07-11 08:02:41 +08:00

- 任务：路径规划前端落地 Phase 1（设计系统与 helper）。
- 代码提交：`b4293563a51d49ec0cecbe2c33a095167d15f709`。
- 修改内容：
  - 扩展前端语义颜色、圆角和 4px 基础间距 Token，并保留旧颜色字段兼容别名。
  - 新增路线标题、核心指标、有效换乘次数、推算时间轴和真实方案差异 helper。
  - 新增 Node 原生 helper 测试脚本与 4 个最小回归测试，不引入第三方依赖。
- 验证：
  - `npm run test:helpers`：通过，4 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android 导出成功。

## 2026-07-07 23:16:02 +08:00

- 任务：ARC-20260707-02 为真实 LLM 调用关闭 Thinking 并限制输出 token。
- 代码提交：`282cb4a117e1cc8e9ff774c0f434d23bbe3412c7`。
- 修改内容：
  - 在真实 LLM Provider 请求体中默认加入 `thinking={"type":"disabled"}`。
  - 新增 `REAL_LLM_MAX_TOKENS` 读取，默认 `800`，非法值或小于 1 时回退默认值。
  - 保留 `temperature=0` 与 `response_format={"type":"json_object"}`。
  - `.env.example` 新增 `REAL_LLM_MAX_TOKENS=800`。
  - `scripts/benchmark_intent_llm_latency.py` 同步生产请求参数，记录 `max_tokens` 与 `thinking_disabled`。
  - 补充 LLM provider 请求体单元测试。
- 验证：
  - `.\.venv\Scripts\python -m py_compile scripts\benchmark_intent_llm_latency.py backend\app\data_sources\llm_providers.py`：通过。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_data_sources.py -q`：通过，15 passed。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_recommendation_engine.py -q`：通过，11 passed。
  - 真实 key 普通短句 smoke：HTTP 200，`finish_reason=stop`，content 非空；model=`glm-4.5-air`，timeout=`45.0`，max_tokens=`800`，thinking_disabled=`true`，total_ms=`4226.2`。
  - 真实 key Intent Parser benchmark：1/1 success；model=`glm-4.5-air`，timeout=`45.0`，max_tokens=`800`，thinking_disabled=`true`，total_ms=`6816.3`。

## 2026-07-07 22:03:06 +08:00

- 任务：ARC-20260707-01 精简并落地 LLM Intent / Recommendation Prompt。
- 代码提交：`8088dddb2e200deaec5e9e1af4aad49be110a426`。
- 修改内容：
  - 重写 Intent Parser、Recommendation、Repair system prompt，改为最小字段契约和明确禁止项。
  - 调整 OpenAI 兼容 LLM provider 的 user prompt 拼接，保留 `response_format={"type":"json_object"}`。
  - Recommendation repair 再次列出合法 `plan_id` 清单，并携带上一轮原始 LLM 输出。
  - 更新推荐引擎测试，覆盖 intent prompt 动态字段、TimePoint 要求、合法 `plan_id` 清单、compact selection payload 和 repair prompt。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_recommendation_engine.py -q`：通过，11 passed。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_api.py -q`：通过，40 passed。
## 2026-07-12 08:41:29 +08:00

- 任务：ARC-20260712-01 实现约束无匹配分析与最近备选。
- 代码提交：未创建；工作区在任务开始前已有大量用户未提交改动，无法在不混入用户内容的情况下安全提交和推送。
- 修改内容：
  - API 与前后端合同升级到 V1.16，新增 `NO_MATCH`、结构化约束分析、覆盖状态、最近备选和 `PLANNING_NO_MATCH` 事件。
  - 新增时间、预算、交通方式、席位/舱位计算器，安全门禁、Pareto 筛选和三赛道确定性选择。
  - 规划器保留过滤前 Provider 候选；无匹配时返回 HTTP 200 + `NO_MATCH`，异步任务映射为 `COMPLETE`。
  - 备选强制不可推荐、不可由 LLM 选择并移除购票跳转；功能开关关闭时回到旧版 `FAILED` 行为。
  - 前端新增独立约束无匹配页面，展示 coverage 与偏差，只有用户确认放宽后才构造新请求重新规划。
  - 增加约束、安全门禁、异步状态、回滚开关和前端请求变换回归测试，重新导出 JSON Schema。
- 验证：
  - `python -m pytest backend/app/tests`：通过。
  - `npm run typecheck`：通过。
  - `npm run test:helpers`：通过，9 passed。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
## 2026-07-12 09:36:27 +08:00

- 任务：ARC-20260712-02 修正地图降级语义并实现结果集席别传播。
- 代码提交：`3f17f50fd1d04bf9c92c9faaa47e5633b9bec96e`。
- 修改内容：
  - 地图 Provider 声明并按交通方式过滤能力，OSRM driving 不再处理地铁、公交或步行请求。
  - 精确路线查询区分首选、备用、规则估算、超时、限流、空结果、未启用、坐标缺失和能力不匹配；只有选中接驳项降级才影响计划与整体 `PARTIAL`。
  - API 与前后端合同升级到 V1.17，新增 `application_scope`、完整 `updated_response` 和结构化 `preference_application`。
  - 新增结果集席别偏好应用器，以目标段合法 option_id 解析权威席别，逐计划逐铁路段匹配各自 option_id、重算费用和舒适度，并剔除不支持席别的推荐候选。
  - 完整快照在校验后一次性更新持久化与内存索引；前端整体替换结果集并保留或安全切换当前方案。
  - 扩展真实地图 smoke、后端回归和前端合同测试，重新导出全部 JSON Schema。
- 验证：
  - `.\.venv\Scripts\python.exe -m pytest backend/app/tests -q`：通过，163 passed。
  - `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_schema_exports.py -q`：通过，3 passed。
  - `npm run test:helpers`：通过，10 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
## 2026-07-12 09:58:11 +08:00

- 任务：参考 Approved 路径规划高保真图，对规划中、方案总览和路线详情进行二次视觉精修。
- 代码提交：`83b23b7b25460012c0557bf4f1f7ddf3f3853ddd`。
- 修改内容：
  - 规划中页面改为高保真稿的横向四阶段卡、聚焦式主内容和独立底部进度面板。
  - 方案总览改为“目的地图 + 深青指标栏”，增加明确的方案选择标题、数据来源层级和带标识的推荐说明。
  - 时间轴使用紧凑白色承载面，窄屏核心价格、耗时和换乘指标不再截断。
  - 路线详情改为线路节点总览、交通方式标签、独立白色分段卡和费用卡，保留所有调整与外部跳转能力。
  - 更新 360、390、430px 总览及 390px 详情视觉回归图。
- 验证：
  - `npm run test:helpers`：通过，10 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
  - 本地浏览器 360×800、390×844、430×932：无横向溢出，核心指标完整，详情分段卡与固定操作区正常。

## 2026-07-12 19:45:40 +08:00

- 任务：ARC-20260712-03 修复规划任务混用无时区与带时区时间导致失败。
- 代码提交：`23ed0e9290a22ebe0010946d4b0de677a7b9db67`。
- 修改内容：
  - `TimePoint` 在 Pydantic 模型边界使用 `ZoneInfo` 统一规范化时区：naive datetime 按声明时区解释，aware datetime 转换到声明时区，并保留或回填 `source_timezone`。
  - 时间约束比较和分钟差统一转换到 UTC，避免不同 offset 或 naive/aware 混用触发异常。
  - 语义校验覆盖时间窗、最早出发、最晚到达、偏好出发时间及硬约束中的全部 `TimePoint`。
  - 异步后台异常使用 `logger.exception` 记录 job/request/trace/correlation ID 与堆栈，用户响应不再包含 Python 内部异常原文。
  - Windows 环境增加 `tzdata` 依赖，为标准库 `zoneinfo` 提供 IANA 时区数据库。
  - 新增模型、LLM 输出、跨 offset 约束计算、异步 API 与日志脱敏回归测试。
- 验证：
  - `.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_models.py backend/app/tests/test_constraints.py backend/app/tests/test_api.py backend/app/tests/test_logging.py`：通过，62 passed。
  - `.\.venv\Scripts\python.exe -m pytest backend/app/tests`：通过，170 passed。

## 2026-07-12 20:20:00 +08:00

- 任务：参考 Approved 高保真稿，修正规划中世界地图缺少进度扫光光晕的问题。
- 代码提交：`7422452f`。
- 根因：当前实现只按进度裁切高亮地图，没有实现高保真稿中位于揭示边缘的独立扫光层，因此边界呈现为硬切线。
- 修改内容：
  - 在 `PlanningProgressScreen` 中增加与 `mapClipWidth` 共用进度源的扫光层，使用 56px 外扩柔光、30px 中层光晕和 4px 高亮核心恢复高保真效果。
  - 将地图揭示区间校准为高保真稿的 32% 至 92%，扫光与裁切边缘始终同步。
  - 在设计系统中新增地图光晕语义色 Token；保留 reduced motion 的即时静态状态更新。
  - 增加 UI 合同测试，并归档 390×844 浏览器视觉回归图。
- 验证：
  - `npm run test:helpers`：通过，11 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
  - 本地浏览器 390×844：扫光亮芯、柔光扩散和地图揭示边缘位置与高保真稿一致。
