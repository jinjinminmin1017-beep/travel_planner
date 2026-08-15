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

## 2026-07-15 23:04:04 +08:00

- 任务：将官方航司查询源从 3 套扩展到 10 套，并收口为 `LICENSE_STATUS` 单变量许可启用。
- 代码提交：`801277574ed3ca2ef658c49ecc7c14d5cfeb3a96`。
- 修改内容：
  - 新增 CA、HNA-micro、ZH、3U、9C、HO、QW 独立契约，合计覆盖 16 个承运人代码；官方 host、入口、已确认 transport、请求/响应字段、动态材料、验证码/限流信号和阻塞原因均逐源登记。
  - 将技术证据门禁与许可门禁分离；航司模板不再显式设置 `ENABLED`/`QPS_LIMIT`，只修改对应 `LICENSE_STATUS=APPROVED` 即自动启用并采用 1 QPS，显式环境覆盖仍可用于紧急停用或限速。
  - 保存 HO、SC 匿名传输结果和 HNA-micro、QW 官方 bundle 契约的脱敏证据；不记录 Cookie、有效 token、设备指纹或用户会话，不绕过验证码或频控。
  - 配置检查、live smoke 和产品能力矩阵改为覆盖完整航司注册表；技术证据不完整时始终 fail-closed。
- 验证：
  - 隔离本机高德环境配置后，`python -m pytest backend/app/tests -q`：213 passed。
  - 航司/配置/能力矩阵专项：34 passed。
  - `python scripts/check_real_api_config.py --tier public`：通过。
  - `python scripts/continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`：3/3 通过，10 套源均被各自技术契约正确阻断。
  - secret 配置检查与单次 live smoke：按设计失败，零真实 offer；当前仍缺可重放匿名库存响应和书面自动化/数据复用批准，未将阻塞伪装为通过。

## 2026-07-16 21:49:56 +08:00

- 任务：将后端数据源运行配置收敛为 ENV 单一配置源。
- 代码提交：`4bb293f`。
- 修改内容：
  - 新增不可变类型化数据源 settings、一次性 ENV 快照与 adapter 注册表，所有 Provider 由集中工厂接收构造参数，移除 Provider 内部分散的环境变量读取。
  - 以 `TRAVEL_DATA_SOURCE_IDS` 和 `TRAVEL_SOURCE_<ID>_*` 作为唯一运行配置结构，严格校验重复源、未知键/adapter、非法类型、host、许可状态和启用源必填项，错误不输出凭证值。
  - 删除 DEV/TEST/PROD 三套 JSON 数据源配置和 `flight_provider_contracts.py`；官方航司技术实现只允许由代码注册，ENV 无法伪造 readiness，未实现源继续 fail-closed。
  - 重建 `.env.example`，增加本地 `.env` 安全迁移脚本，并同步配置检查、benchmark、连续航班 gate、真实 API smoke、项目索引和能力矩阵。
  - 启动阶段同时校验启用且已批准 Provider 的可构造性，禁用 Provider 不创建网络客户端；状态 API schema 保持不变。
- 验证：
  - `\.venv\Scripts\python -m pytest backend/app/tests -q`：214 passed。
  - `\.venv\Scripts\python scripts/check_real_api_config.py --tier public`：通过。
  - FastAPI startup smoke：`/api/health` 与 `/api/data-sources/status` 均返回 200，共加载 26 个数据源。
  - `scripts/continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`：3/3 通过，10 个未实现官方航司源均保持禁用且没有模拟航班。
  - 地图、地点解析和天气真实 smoke 通过；12306 一次真实 smoke 收到上游非 JSON 响应，未伪报成功，铁路 Provider 与规划回归由全量测试覆盖并通过。
  - 旧 JSON、`flight_provider_contracts` 和 `public_airline_contract_ready` 引用检查为空；`git diff --check` 通过。
- 兼容性：未修改 API schema version，未修改数据库和前端，无需数据库迁移。

## 2026-07-16 22:00:48 +08:00

- 任务：清理 `.env` 中没有项目消费者的遗留键。
- 代码提交：`847a7b0`。
- 修改内容：
  - 从本地 `.env` 与 `.env.example` 同步删除未被代码读取的 `POSTGRES_DSN`、`REDIS_URL` 和三个废弃的地理编码 smoke 输入键。
  - 纠正文档中 PostgreSQL/Redis 已可通过环境变量接入的错误描述；当前真实能力为 SQLite 持久化与进程内 TTL 缓存。
  - 保留其他仍被运行代码或 smoke 工具消费的配置，不提交本地 `.env` 和任何凭证值。
- 验证：
  - `.env` 与 `.env.example` 均为 325 个键，键集合差异为 0，目标遗留键剩余 0。
  - `scripts/check_real_api_config.py --tier public`：通过。
  - 数据源与能力矩阵专项测试：20 passed。
  - 全仓运行代码和配置引用检查为空；`git diff --check` 通过。

## 2026-07-16 22:19:55 +08:00

- 任务：按“每个运行配置必须有真实消费者且修改后影响行为”原则收口 Provider ENV。
- 代码提交：`80d387c`。
- 修改内容：
  - 运行数据源从 26 个收敛到 15 个真实可构造源；10 个未实现官方航司查询源与 VariFlight 只保留为能力待办，不再占用 ENV、运行注册表和状态 API。
  - 删除航司 `HTTP_METHOD`、未实现缓存 Provider 的 `CACHE_TTL_SECONDS`、内部计算与纯跳转 Provider 的 `QPS_LIMIT`；adapter-specific loader 会拒绝无行为意义的字段。
  - 新增按 source_id 共享的线程安全 HTTP 请求门控，让地图、地点解析、OSRM、Nominatim、OpenSky、Open-Meteo、LLM 与 12306 的 `QPS_LIMIT` 在真实请求边界生效。
  - 12306 的 `MIN_INTERVAL_SECONDS` 与 QPS 取更严格值，查询缓存 TTL 继续保留并实际控制缓存；LLM benchmark 不能绕过源级 QPS。
  - 修正 `.env` 迁移器，使数据源注册清单和 adapter 结构始终以模板为准，同时安全保留合法本机值与凭证。
- 验证：
  - 后端全量：221 passed。
  - `.env` 与 `.env.example` 均为 151 个键，键集合差异为 0，禁用假字段剩余 0。
  - `scripts/check_real_api_config.py --tier public`：通过。
  - FastAPI startup smoke：`/api/health` 与 `/api/data-sources/status` 均返回 200，状态接口登记 15 个真实运行数据源。
  - 航班 gate 连续 3 次通过：运行 adapter 未登记、请求实现注册表为空。
  - 公开真实接口 smoke 全部通过：地图四种方式、4 条地点解析与接驳、OpenSky、Open-Meteo、12306/航司/地图跳转均成功。
  - `git diff --check` 与 Python 编译检查通过。
- 兼容性：状态 API schema 保持不变，未修改数据库和前端，无需迁移。

## 2026-07-18 07:43:32 +08:00

- 任务：通过官网匿名查询接入春秋航空真实航班、票价和舱位 Provider。
- 代码提交：`1e4413f`。
- 修改内容：
  - 新增 `airline_9c_public_query` 与独立 `spring_airlines_public_query` adapter，使用春秋航空公开订票页实际调用的 `POST /Flights/SearchByTime`，不依赖登录、Cookie、token、签名或验证码材料。
  - 解析 `Route` 航班事实和 `AircraftCabins[].AircraftCabinInfos[]` 舱价事实，金额按 Decimal 转换为分；`Remain=0` 按官网实际展示语义保留为“可售、数量未知”，正整数记录为有限余量。
  - 在真实 `.env` 与 `.env.example` 同步登记并启用 9C：`APPROVED`、1 QPS、60 秒超时、60 秒缓存、host allowlist；两份文件均为 163 个键且键集合一致。
  - 规划请求补充真实城市名，春秋候选按价格和出发时间稳定排序；验证码、人机挑战、HTTP 429、非法 host、业务错误和超时均 fail-closed，不做绕过。
  - 更新公开配置检查、连续门禁、live smoke、项目索引与脱敏验证记录；其他未实现航司仍不能通过 ENV 伪造技术就绪。
- 验证：
  - `\.venv\Scripts\python -m pytest backend\app\tests -q`：223 passed。
  - 航班与配置专项：37 passed。
  - `\.venv\Scripts\python scripts\check_real_api_config.py --tier public`：通过。
  - `\.venv\Scripts\python scripts\continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`：3/3 通过。
  - 真实在线 smoke：`SHA -> CAN`、2026-07-23，Provider 返回 9C8835、CNY 390.00 与真实经济舱可售状态；浏览器匿名结果共 6 班，最低 9C8931、¥370。
  - `git diff --check` 与 Python compileall：通过。
- 兼容性：未修改 API schema、数据库或前端，无需迁移。

## 2026-07-18 08:32:51 +08:00

- 任务：逐一验证除春秋外的 9 家航司，并接入能够由项目后端稳定匿名直连的真实票价 Provider。
- 代码提交：`c894873`。
- 修改内容：
  - 通过真实浏览器验证国航、东航/上航、南航、海航、深航、川航、吉祥、青岛航空和山航官网；再用普通后端 HTTP 客户端逐家复现，记录动态加密、WAF、浏览器指纹和风控材料边界。
  - 新增海航 `airline_hu_public_query` / `hainan_airlines_public_query`：复现官网匿名 deep-link 三步会话，解析服务端页面中的航班、实际机场、时刻、机型、含税总价、舱位和余量。
  - 新增青岛航空 `airline_qw_public_query` / `qingdao_airlines_public_query`：调用匿名初始化接口，按官网公开前端逻辑生成请求材料，解析 JSON 航班、价格、舱位和库存信号。
  - 在真实 `.env` 与 `.env.example` 同步启用 HU、QW，均为 `APPROVED`、1 QPS、60 秒超时、60 秒缓存和严格 host allowlist；两份文件各 183 个键，键集合差异与重复键均为 0。
  - 海航 HTML 快照在入库前删除长加密串、会话字段和不透明动态材料；HTTP 429、验证码、风控挑战、非法 host、业务错误和不支持的响应继续 fail-closed。
  - 国航、东航、南航、深航、川航、吉祥和山航没有登记运行 adapter，也没有写入 ENV；浏览器能够展示价格不等于后端能够稳定复现。
- 验证：
  - `\.venv\Scripts\python -m pytest backend\app\tests -q`：225 passed。
  - 航班与配置专项：39 passed。
  - `\.venv\Scripts\python scripts\check_real_api_config.py --tier public`：通过。
  - `\.venv\Scripts\python scripts\continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`：3/3 通过，9C/HU/QW 均已登记、启用且许可为 `APPROVED`。
  - 项目 Provider 真实在线验收：海航 `BJS -> SHA`、2026-07-23 返回 6 个可售 offer，含 Y87596、HU7607、HU7605、HU7613、HU7601、HU7603，含税最低总价 CNY 550.00；青岛航空 `TAO -> TFU`、2026-07-20 返回 QW9771、CNY 699.00 和 34 个舱价选项。
  - Python compileall、`git diff --check` 和 `.env` / `.env.example` 键集合检查通过。
- 兼容性：未修改 API schema、既有数据库表或前端；本地航班快照 SQLite 继续按需建表，无需迁移。

## 2026-07-19 09:52:54 +08:00

- 任务：启动 ARC-20260719-01，落地东航常驻浏览器航班查询 Phase 1 离线实现基线。
- 代码提交：`c301d82`。
- 修改内容：
  - 新增独立 `browser_worker` Node.js/Playwright 工程、loopback `/v1/flight-search` 与 `/health`、每航司常驻 context/page、串行队列、在途合并、90 秒缓存、短期熔断和分阶段耗时指标。
  - 新增东航/上航 handler；只匹配官方 host 的 `POST /portal/v3/shopping/briefInfo`，联合核对资源类型、JSON 响应、起终点、日期和人数，并严格解析带时区时刻、整数最小货币单位舱价与明确可售信号。
  - 验证码、WAF、限流、超时、密文、过期响应和结构变化全部 fail-closed；只有明确空列表、空计数或空结果状态才返回成功空结果，不记录原始响应、Cookie、Token、设备指纹或完整请求体。
  - 新增 `BrowserWorkerClient` 与 `BrowserAirlineFlightProvider`，后端只允许 loopback worker URL 和显式 host allowlist，并对路线、日期、时区、金额、舱位及可售状态二次校验后转换为现有 `FlightOffer`。
  - 新增 `browser_airline_flight` 类型化 settings 和 `airline_mu_browser_query`；`.env.example` 保持 `PENDING_REVIEW + ENABLED=false`，未确认结果页模板、许可和真实 benchmark 不能通过 ENV 绕过。
  - 更新启动脚本、CI worker 测试、项目索引、架构和产品能力矩阵；外部 API、schema version、数据库和前端合同不变。
- 验证：
  - `\.venv\Scripts\python -m pytest backend\app\tests -q`：229 passed。
  - `browser_worker`：`npm run typecheck` 通过，`npm test` 8 passed，`npm audit` 0 vulnerabilities。
  - `frontend`：`npm run typecheck` 通过，`npm run test:helpers` 11 passed。
  - `\.venv\Scripts\python scripts\check_real_api_config.py --tier public`、Python compileall 和 `git diff --check` 通过。
  - Playwright Chromium 下载未通过：本机网络返回与 `cdn.playwright.dev` 主机名不匹配的证书；未关闭 TLS 校验。由于同时缺经确认的 `MU_RESULT_URL_TEMPLATE` 与许可，未启动真实 worker、未执行 50 次 benchmark，也未将 Phase 1 标记完成。
- 兼容性：不需要数据库迁移，不需要前端同步，不改变 `/api/travel/*`；关闭或不注册 worker 源时既有 9C/HU/QW Provider 与 Planner 降级路径保持不变。

## 2026-07-19 10:22:30 +08:00

- 任务：继续 ARC-20260719-01，完成东航真实结果页、独立 Chromium worker 与低频验收工具。
- 代码提交：`65e38ff`。
- 修改内容：
  - 真实浏览器确认东航单机场直达模板 `https://www.ceair.com/zh/cny/shopping/oneway/{origin_iata}-{destination_iata}/{departure_date}`，并将其作为受 HTTPS 与 `ceair.com` allowlist 保护的默认模板。
  - 新增东航公开结果 DOM 解析：再次核对路线和日期，处理官网公告弹窗，切换并确认“现金-含税”，只映射 `.shopping-simple` 中可验证的 MU/FM 航班、时刻与三类公开舱价。
  - 业务响应与结果卡并行作为查询完成信号；页面结构、税费口径、航班号、路线或日期异常继续 fail-closed，不把挑战或解析失败转换为空航班。
  - 新增目标机 Chrome/Chromium 绝对路径配置，健康接口增加 browser/context/page 分级重建计数；页面关闭只重建 page，context 与 browser 异常按层级恢复。
  - 新增 50 次低频 benchmark 工具，要求用例互不重复并拒绝缓存伪成功，计算成功率、P50/P95/P99、非空结果与挑战；连续 3 次失败或熔断时提前停止，默认额外间隔提高到 10 秒。
  - 更新 `.env.example`、worker README、架构、项目索引、能力矩阵、开发任务与脱敏真实验证证据；外部 API、数据库和前端合同不变。
- 验证：
  - 使用本机 Microsoft Edge Chromium 启动独立 worker，loopback API 真实查询 `PVG -> PEK / 2026-07-23` 返回 MU5151、MU5155、MU5161、MU5163、MU5165；含税最低示例 CNY 550.00，总耗时 3454 ms。
  - 50 次首批验收的前 5 次成功且无缓存命中，P50 4586 ms、P95 5128 ms；随后 3 次超时并触发熔断，已停止访问。真实外部尝试 8 次、成功率 62.5%，未达到 95% 门禁，源继续保持 `PENDING_REVIEW + ENABLED=false`。
  - `\.venv\Scripts\python.exe -m pytest backend\app\tests -q`：229 passed；公开配置检查通过。
  - `browser_worker`：typecheck 通过、11 tests passed、npm audit 0 vulnerabilities。
  - `frontend`：typecheck 通过、helper 11 tests passed；`git diff --check` 通过。
- 兼容性：不需要数据库迁移，不需要前端同步，不改变 `/api/travel/*`；未扩展 Phase 2 航司，既有 9C/HU/QW Provider 与 Planner 降级路径不变。

## 2026-07-19 10:45:19 +08:00

- 任务：继续完成 ARC-20260719-01 的 worker 取消、恢复、风险识别和可观测性任务，并重新执行东航门禁。
- 代码提交：`c378de5`。
- 修改内容：
  - 单次总超时通过 `AbortSignal` 中止后续业务响应等待与 DOM 解析，不再让已超时操作继续进入结果转换。
  - 增加官方 host 的 403/418/429/503 文档、XHR 和 fetch 风险响应监听，供 handler 返回稳定 WAF、限流或挑战错误。
  - BrowserManager 支持注入浏览器启动器，并补齐 page 关闭、context 失效、browser 重启和查询取消的隔离测试。
  - `/health` 新增按 source 的搜索、成功、空结果、挑战、缓存、去重、超时、解析和熔断计数及比率，并输出最多 200 个 cold/warm 样本的 P50/P95/P99。
  - 更新架构、worker README、架构任务、用户任务和脱敏证据；记录第二批 10 秒间隔仍连续超时，以及官方条款未授予自动化和数据复用许可。
- 验证：
  - `browser_worker`：typecheck 通过、16 tests passed、npm audit 0 vulnerabilities。
  - `\.venv\Scripts\python.exe -m pytest backend\app\tests -q`：229 passed；公开配置检查通过。
  - 第二批真实 benchmark 连续 3 次约 15 秒超时后自动停止；可见 Chrome 中同一结果页导航和 DOM 读取也在 30 秒内超时。未继续访问或绕过风险控制。
- 门禁结论：东航尚未完成 50 次且成功率未达到 95%；官方历史声明要求未经同意不得复制或使用网站信息。`airline_mu_browser_query` 继续 `PENDING_REVIEW + ENABLED=false`，Phase 2 按架构约束不能越过东航门禁启动。

## 2026-07-22 23:22:49 +08:00

- 任务：完成 ARC-20260722-01 航班选项可见性与交通方式覆盖语义。
- 代码提交：`85a82f4`。
- 修改内容：
  - 航班 Provider 聚合新增逐来源结构化 outcome，稳定区分成功、确认空结果、429、超时、挑战、非法响应与禁用状态；青岛航空 `code=0 + 未查询到航班` 按确认空结果处理。
  - Planner 为每个来源生成独立失败说明，按请求交通方式范围控制查询和缺失报告；显式排除航班时不触发航班查询，航班暂不可确认但铁路可用时返回 `PARTIAL`，确认空结果不误报系统失败。
  - 前端补齐既有 V1.17 类型，新增铁路/航班独立入口、真实候选筛选、不可用原因、重试状态和功能开关，不生成占位航班、价格、时刻或计划 ID。
  - 保留推荐目标选择器的原有职责，并在交通方式切换、重试与结果集更新后同步有效计划选择。
- 验证：
  - 后端全量：235 passed。
  - 航班 Provider、规划规则与 API 专项：82 passed。
  - 前端 helper/UI 合同：14 passed；TypeScript 检查通过。
  - Expo Web、iOS、Android 导出通过；`git diff --check` 通过。
- 兼容性：外部 V1.17 字段未变化，不需要数据库迁移；旧聚合失败响应由前端保守显示为“暂不可用”。

## 2026-07-24 07:17:50 +08:00

- 任务：完成 ARC-20260724-01 航班城市查询范围与实际机场归一化。
- 代码提交：`03c8232`、`c09b993`。
- 修改内容：
  - 新增城市/机场查询范围模型；春秋、海航固定 `CITY`，青岛航空、东航 Browser 固定 `AIRPORT`，查询范围不能由 ENV 覆盖。
  - 城市范围 Provider 使用各 adapter 自带的显式城市码映射；未知城市不从机场 IATA 推导城市码，只跳过对应 CITY Provider，AIRPORT Provider 仍按 canonical 机场组合查询。
  - Provider 聚合按城市对单次查询或 canonical 机场组合查询，缓存键覆盖 scope、城市码和机场允许集合，并按实际航段事实去重。
  - 春秋分离 `DepartureCode/ArrivalCode` 城市码与 `DepartureAirportCode/ArrivalAirportCode` 实际机场；所有 Provider 缺失实际机场时 fail-closed。
  - 非空候选零 offer 改为 `FLIGHT_PARSER_REJECTED_ALL`，新增原始候选数、规范化数、实际机场、丢弃原因、parser version 和 evidence id 诊断。
  - 交通目录通过受控种子映射补齐 IATA，并在 top-N 前 canonical 化；上海候选稳定为 `SHA`、`PVG` 各一次。
  - Planner 只按响应实际机场构建首末程和中转接驳；跨机场中转要求显式可验证路线和足够衔接时间。
  - 新增脱敏最小春秋问题 fixture，覆盖 4 个 `PVG -> DLC` offer、解析失败语义、查询次数和浦东首程接驳。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests -q`：240 passed。
  - 任务专项：92 passed。
  - `npm --prefix frontend run test:helpers`：14 passed。
  - `npm --prefix frontend run typecheck`：通过。
  - `npm --prefix frontend run build`：Web、iOS、Android 导出通过。
  - `.\.venv\Scripts\python scripts\export_schemas.py` 后 `git diff --exit-code -- schemas`：无差异。
  - Python compileall 与 `git diff --check`：通过。
  - `npm --prefix frontend test`：项目未配置该脚本；已执行实际存在的 `test:helpers`。
  - Ruff：虚拟环境未安装 `ruff`，项目当前无法执行该检查。
- 兼容性：外部 API schema 继续为 V1.17；无数据库迁移、无前端字段变更、未启用东航或 Phase 2 航司。

## 2026-07-26 09:30:00 +08:00

- 任务：完成 ARC-DEV-20260726-01 异步规划假空态、渐进结果、延迟治理与服务端期限。
- 代码提交：`92d7e08`、`e2043c9`、`0e66dd2`、`17c3748`。
- 修改内容：
  - 前端抽出纯规划状态机，使用 elapsed-time 观察窗口、有上限退避与抖动；观察耗尽进入 `OBSERVATION_PAUSED`，继续获取和前台恢复读取同一个 job。
  - 后端新增领域 `PlanningProgressSink`；首个完整安全方案产生后即可保存 `RUNNING + plans非空 + recommendation_result=null` 快照。
  - 异步 store 增加 generation 比较写入和单调进度保护，取消或终态不能被旧 worker 覆盖。
  - 规划内复用地点解析和地图路线；路线键覆盖规范化坐标、方式、Provider 链与环境；铁路/航班直达族最多 2 worker 有界并行。
  - 可观测性增加首个可用方案、最终结果、渐进快照、路线/地点缓存和 deadline 结果。
  - 接入单调时钟服务端期限；默认 180 秒 `observe`，显式 `enforce` 时有完整方案返回 `PARTIAL`、无完整方案返回 `FAILED`。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests -q`：246 passed。
  - `npm --prefix frontend run typecheck`：通过。
  - `npm --prefix frontend run test:helpers`：19 passed。
  - `npm --prefix frontend run build`：Web、iOS、Android 导出通过。
  - Python compileall 与 schema export 无差异检查通过。
- 兼容性：外部 API schema 保持 V1.17；不需要数据库迁移；渐进结果与强制 deadline 有独立开关；未修改或越过航司许可门禁。

## 2026-07-27 09:20:00 +08:00

- 任务：完成 Approved V2 移动端 UI 更新。
- 代码提交：`b8f3b9f`。
- 修改内容：
  - 输入页抽为 `TravelInputScreen`，落地自然语言输入、快捷偏好、脱敏历史与留存偏好面板。
  - 规划页使用纵向阶段、真实进度和候选数量；结果页使用城市级标题、真实候选数和更新时间。
  - 详情页将可靠单段费用、其他费用与权威总价合入连续路线，并保留席别/舱位/接驳调整、收藏、分享、来源、反馈和动态官方渠道跳转。
  - 新增 UI 展示 helper、合同测试和 Approved V2 多尺寸视觉回归资产。
- 验证：
  - 前端 TypeScript 检查通过。
  - 24 个 helper/UI 测试通过。
  - Expo Web/iOS/Android 导出通过。
  - 视觉回归：360、390、393、430px 输入页及 390px 规划、结果、详情页截图完成人工核对。
- 兼容性：不修改外部 API V1.17、数据库、Provider、轮询策略、规划性能与后端运行配置。

## 2026-08-01 07:39:02 +08:00

- 任务：完成 ARC-DEV-20260801-01 首次规划提交首帧误显未输入状态修复。
- 代码提交：`a7c740e`。
- 修改内容：
  - 将客户端规划生命周期扩展为互斥的 `IDLE | SUBMITTING | OBSERVING | PAUSED`，并在纯状态机中为无响应提交期增加 `SUBMITTING` 页面状态。
  - 首次异步 POST 返回前显示专用“正在理解你的行程”界面和受限长度的只读输入摘要，不伪造 `TravelPlanResponse`、地点或服务端进度。
  - 活动 job 返回后才进入 `OBSERVING`；终态与请求失败退出提交态，失败后保留原始输入。
  - 在初始 POST 返回处补充 `planningRunId` 校验，阻止旧请求延迟响应覆盖当前 run。
  - 保留旧结果的重规划继续展示旧结果与局部 busy 状态。
- 验证：
  - `npm --prefix frontend run typecheck`：通过。
  - `npm --prefix frontend run test:helpers`：25 passed。
  - `npm --prefix frontend run build`：Web、iOS、Android 导出通过。
  - `git diff --check`：通过。
- 兼容性：不修改外部 API V1.17、后端、schema、数据库或持久化结构。

## 2026-08-01 07:53:36 +08:00

- 任务：完成 ARC-20260801-02 约束感知候选与可解释备选。
- 代码提交：`b235622`、`9a4008f`、`a37d381`、`524922e`。
- 修改内容：
  - 新增纯函数铁路 offer 预选，完整扫描 Provider 元数据后分桶、稳定排序；删除约束评估前的 first-N 截断，并为正常候选与 relaxation reserve 使用独立构建预算。
  - 最终约束失败或接驳失败时继续尝试后续 offer；日志覆盖原始数、分桶数、构建尝试/成功数、最终合格数和备选数。
  - 时间约束改用门到门 `TravelPlan.departure_time/arrival_time`；缺失所需门到门时间 fail-closed，日志同时记录干线和门到门时刻。
  - 海航 Flight block 支持 1–2 段，严格校验航班、机场、日期、顺序、同机场衔接、最小换乘时间及行程级价格/舱位。
  - NO_MATCH 只读详情展示门到门路线、费用、偏差、确认影响、保留约束、来源、更新时间、风险与缺口；逐航司说明区分有效空、结构不支持、超时、限流、禁用和失败，且不提供购票动作。
  - 新增三处独立功能开关；预选关闭时仍扫描完整事实集，不恢复 first-N 行为。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests -q`：250 passed。
  - `npm --prefix frontend run typecheck`：通过。
  - `npm --prefix frontend run test:helpers`：26 passed。
  - `npm --prefix frontend run build`：Web、iOS、Android 导出通过。
  - Python compileall 与 schema export/diff：通过，无 schema 差异。
  - 低频真实 smoke：春秋航空 `SHA -> CAN` 通过；12306 返回非 JSON 响应，铁路 smoke 失败并保持 fail-closed，未生成模拟事实。
  - `git diff --check`：通过。
  - Ruff：虚拟环境未安装 `ruff`，项目当前无法执行该检查。
- 兼容性：外部 API schema 保持 V1.17；无需数据库迁移；没有启用任何未获许可航司数据源。

## 2026-08-02 07:59:16 +08:00

- 任务：完成 ARC-20260801-03 预算方案席别物化与推荐确定性门禁。
- 代码提交：`13a3a55`。
- 修改内容：
  - 新增有界铁路方案变体物化器，只基于真实可售、有价格的席别生成省预算、更舒适和均衡变体；selected option fingerprint 去重且每个基础行程最多三个变体。
  - Planner 默认选择最低价可售席别，显式席别偏好优先且不可售时保留现有约束解释，不再依赖 Provider 返回顺序。
  - 变体统一重算费用、总时长、席别舒适度与推荐风险状态，确保费用明细、席别、总价和理由一致。
  - 推荐门禁确定性计算 CHEAPEST 和 MOST_COMFORTABLE；BALANCED 仅使用 Pareto 候选，合法但语义错误的 LLM 选择会被后端纠正。
  - 新增两个独立回滚开关，并补充 D3291、四车次最低价、显式席别、Plan ID、Pareto 输入和结果集席别同步回归测试。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests -q`：257 passed。
  - `.\.venv\Scripts\python scripts\export_schemas.py`：导出后 schema diff 无变化。
  - Python compileall 与 `git diff --check`：通过。
  - Ruff：虚拟环境未安装 `ruff`，项目当前无法执行该检查。
- 兼容性：外部 API schema 保持 V1.17；无数据库迁移；航班 Provider、航班配置、限流和 browser worker 无 diff。

## 2026-08-02 FlyAI P0

- 任务：完成 ARC-20260802-01 飞猪 FlyAI 唯一票务事实源代码开发；在线验收保持阻塞。
- 代码提交：见本次提交。
- 修改内容：
  - 根目录固定 `@fly-ai/flyai-cli@1.0.16`；新增 fail-closed CLI client，使用 `shell=False` 参数数组、子进程环境传 Key、输入白名单、总超时、严格 stdout JSON/exit/stderr/business/体验模式门禁和脱敏日志。
  - 新增共用 `fliggy_flyai` OTA Provider，解析直飞/中转航班和铁路 item，只接收精确 Decimal 人民币价格、响应实际舱位/席别与 allowlisted HTTPS `jumpUrl`；相同查询使用 60 秒缓存和 single-flight。
  - 航班与铁路聚合增加 VERIFIED、EMPTY、RATE_LIMITED、TIMEOUT、FAILED、INVALID_RESPONSE、PRICE_NOT_EXACT、DISABLED outcome；FlyAI 失败不触发航司、browser worker 或 12306 fallback。
  - Provider offer 携带 item fingerprint、获取时间和 URL reference；Planner 生成 plan/segment-bound `FLIGGY` redirect，接口只从持久化计划读取并校验归属、allowlist 与过期时间。
  - 外部合同升级到 V1.18，新增 `DataSourceType.OTA` 和 `redirect_type=FLIGGY`；同步后端、JSON Schema、前端类型、LLM schema version 与 API 文档。
  - 前端铁路/航班 CTA 统一为“去飞猪核价并预订”，约束无匹配页识别 FlyAI 票务失败；旧票务源从 ENV 模板、settings model 注册、Provider 注册表、运行聚合与默认启动脚本移除。
  - 新增脱敏航班/铁路 fixture、CLI 红灯、精确价格、缓存、解析、URL allowlist、plan-bound redirect 和发布 benchmark 测试/脚本。
- 验证：
  - `.\.venv\Scripts\python -m pytest backend\app\tests -q`：269 passed。
  - `npm --prefix frontend run typecheck`：通过。
  - `npm --prefix frontend run test:helpers`：26 passed。
  - `npm --prefix frontend run build`：Web、iOS、Android 导出通过。
  - Python compileall、18 个 schema 重导出稳定性、`git diff --check`、敏感信息扫描与 public 配置检查：通过。
  - `@fly-ai/flyai-cli` 安装版本核对：1.0.16。
- 阻塞：仓库根目录 `.env` 未检测到非空 `TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY`；secret 配置检查与 50 样例 benchmark 明确返回阻塞。无 Key 的 Windows CLI 探测在输出体验模式 JSON 后发生 libuv assertion 并非零退出，按门禁不得忽略。
- 兼容性：外部 API 升级到 V1.18；规划请求结构和数据库 schema 不变。历史 `AIRLINE` / `RAIL_12306` redirect 类型仍可解析，但新计划只生成 `FLIGGY`，旧票务源不可通过 ENV 重新启用。

## 2026-08-02 23:34:15 +08:00

- 任务：修复 Windows 真机调试启动时 FlyAI CLI 无法执行的问题。
- 代码提交：`3a272a7`。
- 修改内容：
  - `scripts/device-debug.ps1` 默认启用 `fliggy_flyai`，并把仓库固定安装的 `node_modules\.bin\flyai.cmd` 绝对路径注入后端进程环境。
  - 启动前校验 Windows CLI shim 是否存在；缺失时提示在仓库根目录执行 `npm install`，不在运行期动态下载依赖。
  - 新增 `-SkipFlyAI` 本地回退开关，并同步真机调试命令说明。
- 验证：
  - PowerShell AST 语法解析：通过。
  - 隔离端口启动 `device-debug.ps1 -SkipFrontend -NoWait`：`fliggy_flyai enabled=True, health_status=OK`；测试端口已清理。
  - `.\.venv\Scripts\python -m pytest backend\app\tests\test_fliggy_flyai.py backend\app\tests\test_data_sources.py -q`：30 passed。
  - `git diff --check`：通过。
- 兼容性：外部 API、数据库与前端无变化；未发起真实 FlyAI 票务查询。

## 2026-08-03 08:27:00 +08:00

- 任务：完成 FlyAI CLI 强制退出竞态、来源级熔断与真实运行健康状态开发；在线 50+50 发布门禁保持失败。
- 代码提交：`2d632d7`、`526bbca`。
- 修改内容：
  - 根目录新增固定版本/官方 SHA/补丁 SHA 三重校验的 FlyAI 构建期补丁，只精确替换航班和铁路成功 action 的 `process.exit(0)`；任何版本、片段或 hash 漂移均 fail-fast。
  - Windows 认证运行时直接通过 Node `--single-threaded` 执行 patched bundle，不经 shell；CLI client 自动解析 `.cmd` shim，同时拒绝未认证的锁定包产物；相对 executable 锚定项目根目录，支持从非根工作目录启动。
  - 真机调试增加静态 bundle 校验与真实航班/铁路 readiness；`-SkipFlyAI` 明确关闭票务源，不能显示为 OK。
  - CLI client 增加 fatal process exit、普通非零退出、stderr、timeout、rate limit、business error、invalid JSON/response 和体验模式分类，继续拒绝非零退出的全部 stdout。
  - 新增共享 runtime health registry 与分类熔断：fatal 首次失败立即打开，timeout/rate limit 等使用独立阈值；跨 job 短冷却、半开只允许单 probe，成功后恢复。
  - 数据源状态改用真实运行事件，不再以状态查询时间伪造 `last_success_at`；Provider 降级不影响 `/api/health` liveness。
  - 航班/铁路 outcome 将 runtime/circuit 错误映射为现有稳定失败语义，FlyAI 失败不触发旧航司、12306、browser worker 或模拟事实。
  - benchmark 改为航班、铁路各至少 50 个低频样本，统计成功数、失败分类及 cold/warm P50/P95/P99，任何失败都会使发布门禁失败。
- 验证：
  - 后端全量 pytest：277 passed；FlyAI/状态/API 定向回归：85 passed。
  - 前端 helper tests：26 passed；TypeScript typecheck 通过；Web/iOS/Android Expo export 通过。
  - Schema export diff、Python compileall、Node/PowerShell 语法、bundle patch hash、secret 配置、`git diff --check` 和真实 Key 泄漏扫描：通过。
  - 真实 readiness：修复后航班 10 items / 1344ms，铁路 10 items / 1375ms，均 exit 0；100 次门禁后再次 readiness 遇到普通 exit 1 并按设计阻止真实票务模式启动。
  - 在线门禁：航班 24/50、铁路 23/50 成功；16 次普通非零退出、1 次业务错误、36 次保护性熔断；无 fatal exit。cold P50/P95/P99=1251.63/1458.92/2005.20ms，warm=0.65/0.78/1.13ms。
- 发布结论：代码任务完成，Windows `0xC0000409` 竞态与单 job 故障放大已修复；上游普通 exit 1/业务稳定性未达到全成功门禁，生产真实票务发布继续阻塞。
- 兼容性：外部 API schema 保持 V1.18；无数据库迁移；状态字段语义由配置投影修正为真实运行事件。

## 2026-08-04 23:42:17 +08:00

- 任务：实现本地铁路时刻表快照、直达/一次换乘搜索和 FlyAI 实时核票链路。
- 代码提交：见本次提交。
- 修改内容：
  - 新增默认关闭的铁路快照、本地路由、每日刷新、15 天窗口、新鲜度、保留期和低频间隔配置；非 dry-run 导入与系统调度入口均受开关约束。
  - 新增 12306 当前日期车次发现与完整经停适配器、原子 checkpoint、查询级 resume、临时错误有限退避，以及 429/验证码/访问控制立即暂停门禁。
  - 新增三张 SQLite 快照表、服务日 STAGING/ACTIVE/FAILED/RETIRED 批次、幂等 upsert、完整性与跨日单调门禁、原子激活、差异复制和历史清理。
  - 新增依赖索引的直达/一次换乘搜索、跨日第二程、有界候选与诊断；修正宜兴、福田、北京朝阳等明确/区县强匹配优先级。
  - 新增按日期/起终站分组的 FlyAI 核票器，区分 AVAILABLE、SOLD_OUT、NOT_ON_SALE、PROVIDER_UNAVAILABLE；最多查询 3 组，失败路径 fail-closed。
  - Planner 在快照有效时使用本地候选并只发布 FlyAI 已验证方案；快照不可用回退旧实时路径，本地确认无车不重复外部发现；生成 plan/segment-bound 飞猪跳转。
  - 新增覆盖率、新鲜度、批次、搜索与核票分位数/计数指标，以及 Windows Task Scheduler、cron/systemd、bootstrap/refresh/resume/rollback 运维说明。
- 验证：
  - `python -m pytest backend/app/tests -q`：290 passed。
  - 前端 helper tests：26 passed；TypeScript typecheck 通过；Web/iOS/Android Expo export 通过。
  - Python compileall、PowerShell AST、schema export/diff、`git diff --check` 与硬编码 Secret 扫描通过；Ruff 未安装，无法执行。
  - 真实 G1 dry-run：发现与完整经停查询 HTTP 200，`DRY_RUN_COMPLETE`。
  - 15 天 bootstrap 受控续跑：checkpoint 保留 103 个已完成发现查询、4959 个去重车次和下一前缀 `D10`；随后遇到 12306 访问控制并安全暂停，未激活不完整批次。
- 阻塞：首次 D0～D+14 全量 ACTIVE 建库尚未完成；必须等待 12306 访问控制恢复后从 checkpoint 继续，禁止自动绕过。
- 兼容性：外部 API schema 保持 V1.18；新增 SQLite 表不改写既有计划、响应和反馈表；功能开关默认关闭。

## 2026-08-05 09:03:24 +08:00

- 任务：修复真实铁路 bootstrap 因稀疏来源站序失败。
- 代码提交：`a8c7081`。
- 修改内容：
  - `queryTrainInfo` 的响应行顺序继续作为唯一停站顺序事实，本地 `stop_sequence` 改为响应内连续的 1-based 序号，不再直接使用可能保留父级服务位置的稀疏 `station_no`。
  - 增加 C1017 同型 `station_no=01、07` 的解析回归，验证本地结果为 `1、2`；不补造中间停站，不放宽完整性门禁。
- 验证：真实 C1017 诊断请求 HTTP 200；后端全量 pytest 290 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、票务事实边界或访问控制策略。

## 2026-08-05 09:08:00 +08:00

- 任务：修复真实铁路 bootstrap 的终到站伪发车时间冲突。
- 代码提交：`7b4022a`。
- 修改内容：
  - 首站 arrival 与末站 departure 按服务边界归一为空，避免 12306 终到站残留 `start_time` 被误写为本地事实。
  - 中间站到发时间和跨日时间单调性校验保持不变；增加末站 `arrival=11:32, start=11:31` 的 fail-safe 回归。
- 验证：真实 C119 诊断请求 HTTP 200，并确认香格里拉终到站 `arrival=14:25, start=14:24`；后端全量 pytest 290 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、数据库 schema、访问控制和批次激活门禁。

## 2026-08-05 09:12:00 +08:00

- 任务：避免真实铁路 bootstrap 在确定性失败修复后重复消耗已完成详情请求。
- 代码提交：`bef100c`。
- 修改内容：
  - 新增同服务日批次间的事务型详情批量复制，按 500 个车次分块，复制 service/stop 数据并只在末尾刷新批次统计。
  - `--resume` 遇到 FAILED 批次时创建新 STAGING 批次，只复制 checkpoint 标记完成且来源批次实际存在的稳定车次；失败车次和缺失键不复制，从首个未完成任务继续。
  - checkpoint 在复制完成后立即原子写入，保留旧 FAILED 批次用于审计，不修改 ACTIVE 快照。
- 验证：新增 FAILED 批次本地恢复测试；后端全量 pytest 291 passed；Python compileall 与 `git diff --check` 通过；真实续跑已越过原 C119 失败点。
- 兼容性：不修改外部 API 或 SQLite schema；不增加网络并发、请求频率或访问控制重试。

## 2026-08-05 09:16:00 +08:00

- 任务：补齐真实铁路 bootstrap 遇到的当前官方站点目录缺口。
- 代码提交：`5bfecb3`。
- 修改内容：
  - 使用既有目录导入脚本仅刷新 12306 铁路站点，保留内部种子与 OurAirports 数据；铁路站点总数更新为 3397。
  - 新增的西安东站来自当前官方 `station_name.js`，telecode 为 `XDY`；不猜测站码、不允许空站码入库。
- 验证：`station_code_for_name('西安东') == 'XDY'`；目录/地点/铁路定向测试 31 passed；后端全量 pytest 291 passed；`git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、机场目录或访问控制策略。

## 2026-08-05 11:04:00 +08:00

- 任务：修复真实铁路 bootstrap 对中间站跨午夜停站的错误时间倒序判定。
- 代码提交：`a0402c8`。
- 修改内容：
  - 12306 的 `arrive_day_diff` 继续作为到达日事实；当中间站出发时钟早于同站到达时钟时，将出发日偏移规范化到次日。
  - D10 南京站 `23:56` 到、`00:02` 发可表达为第 0 天到达、第 1 天出发；不放宽跨站时间单调性、批次完整性或原子激活门禁。
  - 扩展 Provider 回归 fixture，同时覆盖稀疏来源站序、跨午夜停站和终到站伪发车字段。
- 验证：真实 D10 单次低频详情请求 HTTP 200；铁路定向测试 14 passed；后端全量测试 290 passed、1 个无关异步规划用例首次失败且单独重跑 1 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、请求频率、并发度或访问控制策略。

## 2026-08-05 17:05:00 +08:00

- 任务：修复首次建库整窗 `--resume` 重复处理已 ACTIVE 服务日。
- 代码提交：`88d68c8`。
- 修改内容：
  - Bootstrap resume 在发现和详情请求前查询 SQLite ACTIVE；已激活日期直接跳过，并用 ACTIVE batch 修复 checkpoint 的批次、状态、计数和完成车次集合。
  - Refresh 模式不走跳过分支，保留既有差异刷新语义；新鲜度查询接口允许调用方显式选择“不做新鲜度过滤”，其他本地路由调用仍保留原新鲜度门禁。
  - 增加已 ACTIVE + 损坏 checkpoint 场景的零网络回归，确保不会再次创建重复详情请求。
- 验证：铁路定向测试 15 passed；后端全量测试 292 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API 或 SQLite schema；减少重复网络请求，不改变低频间隔、并发度或访问控制策略。

## 2026-08-05 21:05:00 +08:00

- 任务：修复真实 C824 详情混入父级服务残留停站导致的时间倒序。
- 代码提交：`6bd8100`。
- 修改内容：
  - 当详情停站数多于发现接口的 `total_num` 时，对中间行使用首站时钟、到达日偏移和来源 `running_time` 做保守一致性对账。
  - 仅在被删行偏差至少 30 分钟且全部保留行偏差不超过 15 分钟时剔除恰好超出的行；首末站不可删除，证据不足继续失败关闭。
  - 增加 C824 同型 3 站发现、4 行详情回归，验证父级残留行被移除且本地站序重新连续化。
- 验证：真实 C824 低频诊断 HTTP 200；铁路定向测试 16 passed；后端全量测试 293 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、请求间隔、并发度或访问控制策略。

## 2026-08-06 08:05:00 +08:00

- 任务：避免 Windows 短暂文件共享冲突中断铁路 checkpoint 原子保存。
- 代码提交：`2fae4e7`。
- 修改内容：
  - checkpoint 仍先完整写入同目录 `.tmp`，再执行原子 replace；仅对 Windows `PermissionError` 增加最多 6 次、50～800ms 的有界指数退避。
  - 持续占用达到重试上限后继续明确失败；不捕获其他磁盘、权限或数据错误，不降低 checkpoint JSON 完整性。
  - 增加两次瞬时共享冲突后成功的回归测试，验证最终文件可读。
- 验证：铁路定向测试 17 passed；后端全量测试 294 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、12306 请求频率、并发度或访问控制策略。

## 2026-08-07 19:05:00 +08:00

- 任务：修复铁路发现完成后车次撤回导致 bootstrap 确定性失败。
- 代码提交：`d7a285c`。
- 修改内容：
  - 详情响应缺少至少两个停站时，使用同日期、同车次号做一次低频精确发现复核；仅当精确结果也确认该车次已不存在时，归类为发现后的撤回服务。
  - Bootstrap 从 checkpoint 的发现集合中移除已确认撤回的稳定任务键，更新完整性期望数后继续；精确发现仍存在、身份不确定或 checkpoint 无法对账时继续失败关闭。
  - 访问控制异常仍直接上抛并暂停；未增加并发，也没有绕过验证码、429 或安全挑战。
- 验证：真实 C4248 详情 HTTP 200 但无 `data.data`，随后精确发现返回 0 条；铁路定向测试 20 passed；后端全量测试 297 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API 或 SQLite schema；所有入库服务仍要求至少两个合法停站并通过原子批次完整性门禁。

## 2026-08-07 22:05:00 +08:00

- 任务：修复铁路发现摘要少计一站导致完整详情被误判为父交路残留。
- 代码提交：`bb478c5`。
- 修改内容：
  - 详情仅比发现 `total_num` 多一站时，增加“全部行车次号一致、首末站匹配、全行累计运行时偏差不超过 15 分钟”的完整服务证据路径。
  - 满足全部证据时保留详情的完整停站；否则继续走原有异常中间行对账，证据不足仍失败关闭。
  - C824 的 65 分钟异常行仍被原规则剔除；D8813 的 5 个同车次合法停站不再为匹配错误的 `total_num=4` 丢失任一站。
- 验证：真实 D8813 低频详情诊断为 5 行，累计运行时偏差 2～6 分钟；铁路定向测试 21 passed；后端全量测试 298 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、请求间隔、并发度或访问控制策略；不放宽首末站、车次身份、时间或批次原子激活门禁。

## 2026-08-08 13:05:00 +08:00

- 任务：避免当前官方目录尚无 telecode 的新站点阻塞整个铁路服务日导入。
- 代码提交：`2ea69ed`。
- 修改内容：
  - 将“站名存在但本地当前官方目录无 telecode”区分为显式 `RailTimetableUnsupportedStationError`；空站名和其他解析错误继续按原规则失败。
  - Bootstrap 只对命中该异常的单一服务执行失败关闭，把车次、站名和 `UNSUPPORTED_STATION` 原因写入 checkpoint 隔离清单，并从本批可入库发现集合移除；不生成或猜测站码。
  - 其余服务继续完成原子批次；隔离条目保留可审计原因，不进入本地路线候选。
- 验证：当前官方 `station_name.js`（3397 站）和官方全站起售目录（3169 站）均无“玉环”；G7364 精确发现仅提供站名、未提供 telecode；铁路定向测试 22 passed；后端全量测试 299 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改外部 API、SQLite schema、请求间隔、并发度或访问控制策略；无法用官方 telecode 表示的服务不会进入 ACTIVE 运行图。

## 2026-08-14 — 新增 Codex Task Dock 桌面辅助工具

- 任务：实现方案 B 的浅色开发任务侧栏，并停靠在 Codex 左侧。
- 代码提交：未提交，保留在当前工作区供用户审阅。
- 修改内容：
  - 在 `tools/codex-task-dock/` 新增独立 Python 标准库服务、Edge App 界面与 Win32 停靠控制，不依赖旅行项目业务运行时。
  - 每 3 秒检查目录 mtime 与已知任务文件的 `mtime + size`，只重新读取变化文件；目录变更时重枚举，并提供 60 秒兜底枚举。
  - Codex 在临时 worktree 中执行；当前未提交文件先形成上下文快照，任务结果再以独立 binary patch 应用到主工作区。
  - 状态灯通过 Git 正向与反向补丁校验判断待开发、开发中、已完成或漂移；Revert 只反向应用单任务补丁，冲突时停止。
  - 删除操作只移除任务源文档中的对应记录，先校验源行签名，不回退或删除代码。
  - 界面采用浅色焦点任务方案，无添加任务控件，支持键盘焦点、原生确认弹窗、窄宽度与低高度适配。
- 验证：Task Dock 单元与本地 API 测试 7 项通过；Python compileall、JavaScript 语法检查、380x900 与 300x700 浏览器布局检查通过，无水平溢出。
- 兼容性：未修改旅行 API、SQLite schema、后端服务或业务前端；工具状态与补丁存放在 `%LOCALAPPDATA%\CodexTaskDock`。

## 2026-08-15 — 修复 Task Dock 周期性弹出终端窗口

- 任务：消除 Task Dock 后台同步 Git 状态以及运行 Codex 时创建可见控制台窗口的问题。
- 代码提交：未提交，保留在当前工作区供用户审阅。
- 修改内容：
  - 新增跨平台子进程标志模块；Windows 使用 `CREATE_NO_WINDOW`，其他平台保持默认行为。
  - Git 状态检查、Codex CLI 执行和 Edge App 启动统一传入隐藏控制台标志。
  - 增加回归测试，校验 Git 子进程在 Windows 上确实携带无窗口标志。
- 验证：Task Dock 自动测试 8 passed；Python compileall 与 `git diff --check` 通过。
- 兼容性：不修改任务文档扫描频率、补丁状态语义、旅行 API、数据库或业务前端。

## 2026-08-15 — Task Dock 新增一键开发全部任务

- 任务：在 Task Dock 中增加一个按钮，把当前所有待开发任务自动交给 Codex。
- 代码提交：未提交，保留在当前工作区供用户审阅。
- 修改内容：
  - 新增顺序批量队列，只收集实际代码状态为待开发的任务，并在每次启动前重新读取任务原文。
  - 每条任务继续使用独立 worktree 和独立补丁；上一条结束并完成状态校验后，才开始下一条。
  - 汇总区新增“一键开发全部”按钮，运行时展示总数、已处理数、失败数、跳过数和剩余数。
  - 队列运行时可停止后续任务；正在运行的 Codex 不被强制终止，保证当前补丁安全收尾。
  - 批量运行期间禁用单任务开发、Revert 和删除，避免队列与人工操作交叉修改代码。
- 验证：Task Dock 自动测试 26 passed；JavaScript 语法检查、Impeccable UI 检测、406x868 与 320x720 浏览器布局检查通过。
- 兼容性：仍然只允许一个 Codex 任务同时写代码；不修改旅行 API、数据库或业务前端。

## 2026-08-15 — Task Dock 任务列表增加状态筛选

- 任务：为“其他任务”列表增加基于任务状态的可选筛选。
- 代码提交：未提交；`tools/codex-task-dock/` 在当前工作区原本为未跟踪目录，避免擅自提交用户既有内容。
- 修改内容：
  - 增加“全部状态、待开发、开发中、已完成、需检查”单选下拉框，默认保持全部显示。
  - 筛选只作用于浏览器显示层，不修改任务状态、任务文档或后端 API；当前焦点任务保持可见。
  - 筛选后显示“匹配数 / 其他任务总数”，并提供对应空状态文案和键盘焦点样式。
  - 增加 Web 静态契约测试，覆盖状态选项与筛选事件绑定。
- 验证：`node --check tools/codex-task-dock/web/app.js` 通过；Task Dock 自动测试 9 passed。
- 兼容性：不修改旅行 API、SQLite schema、任务扫描器或任务执行/回退流程。

## 2026-08-15 — 修复 Task Dock 状态下拉框闪退

- 问题：点击状态筛选后，Edge 原生下拉框一闪而过，无法选择。
- 根因：停靠线程每 0.3 秒重复调整 Task Dock 的窗口层级；原生下拉框是 Edge 独立前台弹层，窗口重排会使其立即失焦关闭。
- 修复：当 Task Dock 主窗口或同一 Edge 进程的原生弹层位于前台时，暂停本轮显示、定位和置顶操作；切回 Codex 后继续正常跟随停靠。
- 测试：新增停靠交互回归测试，覆盖主窗口前台、Edge 原生弹层前台和 Codex 前台三种情况。
- 代码提交：未提交；`tools/codex-task-dock/` 在当前工作区原本为未跟踪目录。
## 2026-08-15 — 修复 Task Dock 任务选择与详情错位

- 任务：修复点击“其他任务”后焦点详情显示其他同编号任务的问题。
- 代码提交：未提交；`tools/codex-task-dock/` 在当前工作区原本为未跟踪目录。
- 修改内容：
  - 将任务的界面显示编号与内部唯一标识分离；显式编号按来源文档生成稳定、唯一的内部 ID。
  - 详情仍显示原始任务编号，选择、执行、回退和删除使用内部唯一 ID。
  - 增加跨文档重复 `P0-1` 的精确选择回归测试及 Web 展示契约检查。
- 验证：Task Dock 自动测试 13 passed；当前 79 条真实任务的内部重复 ID 为 0；Python compileall、JavaScript 语法检查与 `git diff --check` 通过。
- 兼容性：不修改旅行规划 API、SQLite schema 或任务文档内容。
## 2026-08-15 — Task Dock 改为完整任务列表与详情联动

- 任务：调整任务列表交互，使点击任务只更新上方详情，不再从下方列表移除该任务。
- 代码提交：未提交；`tools/codex-task-dock/` 在当前工作区原本为未跟踪目录。
- 修改内容：
  - “其他任务”改为“全部任务”，列表始终保留所有符合当前状态筛选的任务。
  - 点击任务后只更新上方详情；当前任务在列表原位置保留，并通过完整轮廓、浅色背景和 `aria-pressed` 表达选中状态。
  - 状态筛选计数改为基于完整任务列表，空状态文案同步去除“其他任务”语义。
  - 增加静态交互契约回归，防止后续重新排除当前任务。
- 验证：Task Dock 自动测试 13 passed；Python compileall、JavaScript 语法检查与 `git diff --check` 通过。
- 兼容性：不修改任务扫描器、任务状态、旅行规划 API 或 SQLite schema。

## 2026-08-15 — Task Dock 任务详情支持定位原文

- 任务：在任务详情中增加跳转到任务出处的操作。
- 代码提交：未提交；`tools/codex-task-dock/` 在当前工作区原本为未跟踪目录。
- 修改内容：
  - 新增次级按钮“定位到任务原文”，点击后通过本地受权接口在 VS Code 中打开来源 Markdown，并定位到任务标题行。
  - 打开前重新校验任务仍由扫描器识别、来源文件仍存在且位于 `docs/Dev`，不接受任意本机路径。
  - 增加请求中禁用、成功与失败反馈，以及窄屏单列布局。
  - 增加本地 API 与 Web 静态契约回归测试。
- 验证：Task Dock 自动测试 16 passed；JavaScript 语法、Python compileall、`git diff --check` 和重启后的本地健康检查通过；运行中页面已包含新按钮。
- 兼容性：不修改任务文档内容、任务状态、旅行规划 API 或 SQLite schema。

## 2026-08-15 — 修复 Task Dock 原文按钮未实际跳转

- 问题：原文按钮返回成功提示，但 VS Code 没有打开来源文件或跳转到标题行。
- 根因：`code.cmd` 的安装路径包含空格，旧的 `cmd.exe /c` 分离参数方式实际退出码为 1；异步启动又吞掉了该失败。
- 修复：改用正确引用的完整 Windows 命令行，显式传入 `--reuse-window --goto`，并等待校验命令结果；按钮文案同步改为“跳转到任务原文”。
- 验证：Task Dock 自动测试 17 passed；真实跳转打开 `task_from_user_for_dev.md:1`，VS Code 活动窗口标题与目标文件一致；JavaScript 语法、Python compileall 与 `git diff --check` 通过。
- 兼容性：继续只允许跳转扫描器已识别的 `docs/Dev` 来源文件，不修改文档和任务状态。

## 2026-08-15 — 修复 Task Dock 启动 Codex 退出码 2

- 问题：任务交给 Codex 后立即以退出码 2 失败。
- 根因：Codex CLI 0.128.0 的审批参数必须放在 `exec` 子命令之前，旧命令顺序已不兼容。
- 修复：生成 `codex -a never exec --ignore-user-config ...` 命令，同时修复 `.cmd` 和 `.ps1` 两条启动路径；复用登录凭证但隔离不兼容的个人配置；关闭后台 stdin，防止 CLI 等待不存在的附加输入；失败时把真实错误摘要回传详情区。
- 验证：Task Dock 自动测试 22 passed；本机 CLI 参数兼容性检查返回 0；真实重试已进入 Codex `thread.started` / `turn.started`，任务保持运行且无错误；Python compileall、JavaScript 语法与 `git diff --check` 通过。
- 兼容性：保持 `workspace-write` 沙箱和 `never` 审批策略，不扩大文件权限或任务并发度。

## 2026-08-15 — 补齐 Task Dock 开发结果回传与状态恢复

- 问题：Codex 已结束但 Dock 仍显示“开发中”，且一次 Windows `.cmd` 调用没有把具体任务正文交给 Codex。
- 根因：旧实现只有运行线程末尾的内存状态更新，没有持久化完成回执与重启恢复；多行提示词作为 `.cmd` 参数传递也不可靠。
- 修复：任务正文改由 stdin 输入；新增每次运行的原子 JSON 结果回执，记录 PID、日志、退出码、结果摘要、worktree 和补丁；启动时恢复遗留运行任务，校验 JSONL 完成事件和实际 Git diff，成功则应用补丁并点亮绿灯，无改动或未完成则转为可重试失败；完成详情显示 Codex 最终摘要。
- 代码提交：未提交；保留在当前工作区供用户审阅。
- 验证：Task Dock 自动测试 28 passed；新增两个中断恢复回归，本机 Codex CLI 帮助确认 stdin 协议。
- 兼容性：不修改旅行规划 API、SQLite schema、任务扫描频率或串行执行策略。
