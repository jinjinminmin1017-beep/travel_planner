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
