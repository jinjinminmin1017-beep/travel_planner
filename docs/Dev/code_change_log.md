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

## 2026-07-12 20:28:06 +08:00

- 任务：以 Approved HTML 高保真稿为唯一视觉验收标准，重新实现规划中页面。
- 代码提交：`79d9b83`。
- 根因：上一版为了避免新增依赖，以三层半透明 View 近似 CSS 渐变，无法形成与 HTML `linear-gradient()` 一致的连续透明度；同时地图尺寸、背景、阶段卡、进度区和全屏结构仍存在数值偏差。
- 修改内容：
  - 引入 Expo SDK 54 兼容的 `react-native-svg`，将 HTML 的线性渐变、径向背景渐变和扫光三个色标直接转换为跨 Web/iOS/Android 的 SVG 渲染。
  - 精确映射 42px 扫光宽度、`rgba(126, 233, 212, 0.22)` 中心色、32% 至 92% 位移、5 秒 `cubic-bezier(0.2, 0.8, 0.2, 1)` 节奏。
  - 校准 214px 地图高度、`#183c42` 底色、0.94 地图透明度、31px 标题、阶段卡间距与状态色、白色进度面板和 4px 进度条。
  - 规划等待期间使用全屏内容布局并隐藏底部主导航，与 Approved 规划中页面结构保持一致；实际业务进度与 reduced motion 行为继续保留。
  - 更新设计 Token、UI 合同测试和 390×844 视觉回归图。
- 验证：
  - `npm run test:helpers`：通过，11 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
  - 本地浏览器验证 SVG 渐变节点、42px 扫光尺寸、移动边界与页面结构均已生效。
- 依赖审计：`npm audit --omit=dev` 报告 Expo 依赖树内 12 个 moderate、1 个 high 已知问题；自动强制修复会升级至 Expo 57，属于破坏性架构升级，本任务未执行。

## 2026-07-13 22:32:50 +08:00

- 任务：ARC-20260712-04 接入高德地点搜索并移除接驳规则估算。
- 代码提交：`7603cf3f`。
- 修改内容：
  - 新增独立的 `amap_geocode` 与 `amap_place_search` Provider，复用既有高德 Web Service key，并同步 DEV/TEST/PROD 配置和环境变量模板。
  - `resolve_location_point()` 改为结构化解析，支持城市上下文、本地已验证坐标、高德地址解析、高德 POI 搜索、精确候选消歧和 TTL 缓存；目录节点缺坐标时继续在线解析。
  - 接驳引擎只保留地图 Provider 返回且通过距离、耗时、费用校验的方式；删除固定分钟、距离、费用和 OSRM 规则费用估算，新结果不再生成 `RULE_ESTIMATED`。
  - 必需接驳没有可验证方式时阻断对应门到门候选，聚合重复失败并返回结构化 `SourceFailure`；历史规则估算方案禁止直接重算。
  - 前端过滤 `UNAVAILABLE` 接驳选项，不补默认数字；同步 nullable 步行距离类型和 JSON Schema。
  - 真实 API smoke 覆盖“温州永嘉桥头梨村 → 温州南站”及“武汉站/武汉东站/汉口站 → 武汉新天地”的地点解析和高德驾车路线。
- 验证：
  - `.\.venv\Scripts\python.exe -m pytest backend/app/tests -q`：通过，177 passed。
  - `npm run typecheck`：通过。
  - `npm run test:helpers`：通过，11 passed。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
  - 临时启用已获批的新增高德能力开关执行 `scripts/live_smoke_real_apis.py --provider geocode`：4 条真实路线全部通过；未修改或提交 `.env` 与真实 key。

## 2026-07-13 23:14:33 +08:00

- 任务：移除规划中页面底部“当前进度”加载面板。
- 代码提交：`92b18b3`。
- 修改内容：
  - 删除“当前进度”标题、动态状态文案和进度轨道，避免与四阶段状态卡重复表达。
  - 移除不再使用的 `statusText` 组件参数、调用方传值、进度样式及设计 Token。
  - 保留真实规划进度驱动的地图揭示动画、扫光和四阶段状态映射。
  - 补充 UI 合同断言，防止进度面板重新出现。
- 验证：
  - `npm run test:helpers`：通过，11 passed。
  - `npm run typecheck`：通过。
  - `npm run build`：通过，Expo iOS / Android / Web 导出成功。
  - 本地浏览器规划状态：`当前进度` 不再渲染，地图和四阶段状态正常存在。

## 2026-07-14 12:05:53 +08:00

- 任务：ARC-20260714-01 修复铁路中转候选提前截断与同站接驳误建模。
- 代码提交：`bdff0d67300a04676da2ba3ac45131575850d4fb`。
- 修改内容：
  - 新增 `rail_connection_matcher.py`，对 Provider 完整 offer 集按稳定事实键去重、排序并建立第二程发车索引，使用二分查找和最大等待窗口生成验证后候选。
  - `RailOffer` 保留 12306 起终站电报码；同站连接只按稳定 station code 判定，不调用地图 Provider，也不生成虚构的站间接驳段。
  - 跨站或站点身份不明确时必须取得真实地图接驳段，换乘门槛取 45 分钟安全下限与“出站缓冲 + 地面接驳 + 进站缓冲”的较大值。
  - 规划器先汇总所有中转站候选，再按安全、硬约束、到达时间、总耗时、等待、费用、风险和稳定键排序，最后应用 `max_plans`。
  - 增加 `RAIL_CONNECTION_NOT_FOUND` 独立错误语义、逐中转路线诊断指标和安全默认配置；功能开关关闭时回退到旧的前 2×2 offer 窗口。
  - 新增完整候选、G502 + D6649、44/45 分钟、360/361 分钟、同站/跨站、去重、配置回退和错误语义回归测试。
- 验证：
  - 标准 TEST 配置下 `\.venv\Scripts\python -m pytest backend\app\tests -q`：通过，187 passed。
  - `\.venv\Scripts\python scripts\export_schemas.py`：通过，`schemas/` 无差异。
  - `\.venv\Scripts\python scripts\check_real_api_config.py --tier public`：通过。
  - `\.venv\Scripts\python scripts\live_smoke_real_apis.py --tier public`：通过，地图、地点解析、航班动态、天气和 redirect-only Provider 全部成功。
  - `git diff --check`：通过。

## 2026-07-14 22:06:23 +08:00

- 任务：ARC-20260714-02 修复高德公交空费用导致异步规划崩溃。
- 代码提交：`5da3564859b66e1d33c7f0ffab4dbc878bb52f81`。
- 修改内容：
  - 地图费用解析改用 `Decimal` 完成元到分转换；`None`、空字符串和空数组保留为未知费用，禁止回填 0 元或模拟金额。
  - 非空数组、对象、布尔值、负数、非有限值和非法字符串统一转换为 `MAP_ROUTE_RESPONSE_INVALID`，公交费用与出租车费用复用同一解析规则。
  - 地图 Provider 调度边界隔离 `ValueError`、`TypeError` 和 `KeyError`，记录不含原始响应、密钥和 URL 的结构化日志，并继续兼容的后备 Provider。
  - 增加费用输入矩阵、空公交费用事实保留、日志脱敏、后备 Provider、接驳方式隔离和异步规划终态回归测试。
- 验证：
  - 标准 TEST 配置下 `\.venv\Scripts\python -m pytest backend\app\tests\test_map_providers.py backend\app\tests\test_local_transfer_engine.py backend\app\tests\test_api.py -q`：通过，77 passed。
  - 标准 TEST 配置下 `\.venv\Scripts\python -m pytest backend\app\tests -q`：通过，207 passed。
  - `\.venv\Scripts\python scripts\export_schemas.py`：通过，`schemas/` 无差异。
  - `git diff --check`：通过。

## 2026-07-14 22:50:22 +08:00

- 任务：ARC-20260714-02 将结果集席别传播修正为同车次同步。
- 代码提交：`a8c9c91a786e12969eb177926beb1a0df8e92ccd`。
- 修改内容：
  - 以规范化 `train_number` 为席别同步键，只更新结果集中包含目标车次的铁路段；同一方案内其他车次和不包含目标车次的方案保持不变。
  - 同车次跨方案分别匹配各自合法 seat option，独立刷新价格、费用、舒适度和数据质量。
  - 仅同车次缺少目标席别的方案进入 `unsupported_plan_ids`；成功重新选择后恢复旧逻辑误标的推荐资格。
  - 移除车次级操作对全局 `TravelRequest.preferred_rail_seat` 和 `preference_source` 的改写，更新成功提示为具体车次同步结果。
  - 更新 API 契约、架构、开发任务和测试任务，并增加同车次、不同车次及 G834 + K597 中转回归覆盖。
- 验证：
  - `backend/app/tests/test_api.py`：47 passed。
  - 同车次与不同车次专项回归：2 passed。
  - `npm run typecheck`：通过。
  - `npm run test:helpers`：11 passed。
  - `python scripts/export_schemas.py`：通过，`schemas/` 无差异。
  - 后端全量：205 passed、3 failed；失败为本机高德地理编码启用状态与既有默认禁用断言冲突，与本次席别改动无关。
## 2026-07-15 08:30:00 +08:00

- Task: official-airline anonymous sampling, redacted evidence, independent contracts, risk controls, terms review and continuous smoke.
- Implementation commit: `d1aa196`.
- Result: MU/CZ/SC remain disabled and `PENDING_REVIEW`; three safety-gate smoke iterations and 212 backend tests passed. Live offer smoke remains blocked until written authorization and executable endpoint contracts are available.
