# Time Performance Optimization

更新日期：2026-07-06

本文作为旅行规划链路时间性能优化专项记录，持续记录沟通结论、耗时假设、测试方法、测试结果和后续任务。

## 背景

- 2026-07-05 真机链路样本中，用户从提交规划到后端完成完整结果约 104.5 秒，前端轮询感知最多再增加约 1.2 秒。
- 样本拆分：
  - `POST /api/travel/plan/async` 前置自然语言解析阶段约 45.492 秒。
  - 后台规划 job 从 `created_at=2026-07-05T10:38:18.941+08:00` 到 `updated_at=2026-07-05T10:39:17.936+08:00`，约 58.995 秒。
  - 推荐 LLM 日志显示约 33.530 秒。
- 对话中确认：用户不接受通过“先返回 job、解析放后台”来掩盖 LLM 解析慢，也不接受“规则先规划、LLM 后规划一遍”的双规划方案。
- 当前专项聚焦：解释并验证“为什么一句话意图解析会等到 45 秒”，先定位 LLM 解析本身的性能问题。

## 当前已知链路

- `backend/app/main.py` 的 `plan_travel_async()` 在创建 async job 前调用 `parse_travel_request_with_validation()`。
- `backend/app/services/intent_parser.py` 优先调用真实 LLM；发生 `httpx.HTTPError`、`LLMProviderError` 或 `ValueError` 后降级到规则解析。
- `backend/app/data_sources/llm_providers.py` 当前所有 LLM 用途共用：
  - `REAL_LLM_MODEL`
  - `REAL_LLM_BASE_URL`
  - `REAL_LLM_TIMEOUT_SECONDS`
- 当前 `.env` 中 LLM 配置：
  - `REAL_LLM_MODEL=glm-5.2`
  - `REAL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`
  - `REAL_LLM_TIMEOUT_SECONDS=45`
- 意图解析 prompt 文件为 `backend/app/llm/prompts/intent_parser_prompt_v1_0.txt`，当前约 3951 字符、71 行；2026-07-07 架构口径已要求按最小字段契约精简。
- 当前 LLM 请求包含 `response_format={"type":"json_object"}`，未设置 `max_tokens`。

## 沟通结论

- 单独拆 timeout 不能让正常请求更快，只能把远端卡住时的最坏等待从 45 秒缩短到更小值。
- 本轮日志里的 45 秒不是“模型认真解析一句话用了 45 秒”，而是 `The read operation timed out`，即调用等到超时上限才失败。
- 真正需要验证的点：
  - 供应商或模型是否存在高波动或长尾卡顿。
  - 当前长 prompt 是否影响首包或总耗时。
  - `response_format=json_object` 在 GLM OpenAI-compatible 接口上是否造成兼容性或延迟问题。
  - 未设置 `max_tokens` 是否扩大生成空间，增加异常拖长风险。
  - 是否需要为 intent parse 使用低延迟模型或更短 prompt。

## 专项测试设计

第一阶段先做 50 次当前配置基线压测：

- 脚本：`scripts/benchmark_intent_llm_latency.py`
- 样本输入：`明天从上海东方明珠塔到成都太古里，高铁优先，上午出发`
- 测试次数：50
- 默认使用当前 `.env` 的模型、base URL 和 timeout。
- 记录字段：
  - run 序号
  - model
  - base_url host
  - timeout seconds
  - 是否启用 `response_format`
  - 是否设置 `max_tokens`
  - system prompt 字符数
  - user prompt 字符数
  - request body bytes
  - time_to_headers_ms
  - body_read_ms
  - json_schema_semantic_ms
  - total_ms
  - status / error_type / error_message 摘要
- 安全要求：
  - 不记录 API key。
  - 不记录完整 LLM 输出。
  - 不记录完整用户隐私输入，仅记录输入长度。

后续对照测试建议：

- 当前 prompt + `response_format` + 无 `max_tokens`。
- 当前 prompt + 无 `response_format`。
- 当前 prompt + `max_tokens=800`。
- 精简 prompt + `response_format` + `max_tokens=800`。
- 当前模型与低延迟模型对比。

## 测试结果

### 2026-07-06 基线 50 次压测

- 测试命令：
  - `.\.venv\Scripts\python .\scripts\benchmark_intent_llm_latency.py --runs 50 --label baseline_50`
- 测试日志：
  - `logs/intent_llm_perf_20260706-222853_baseline_50.jsonl`
  - `logs/intent_llm_perf_20260706-222853_baseline_50_summary.json`
- 测试配置：
  - model：`glm-5.2`
  - base_url host：`open.bigmodel.cn`
  - timeout：45 秒
  - `response_format={"type":"json_object"}`：启用
  - `max_tokens`：未设置
  - system prompt：2761 字符
  - user prompt：273 字符
  - request body：4724 bytes
  - raw input：26 字符

结果汇总：

| 指标 | 结果 |
| --- | ---: |
| 总次数 | 50 |
| 成功次数 | 3 |
| 失败次数 | 47 |
| 成功率 | 6% |
| 全量平均耗时 | 35123.6 ms |
| 全量中位耗时 | 33303.2 ms |
| 全量 P90 | 45060.3 ms |
| 全量 P95 | 46285.7 ms |
| 全量最小耗时 | 13946.1 ms |
| 全量最大耗时 | 47018.8 ms |
| 成功平均耗时 | 32144.0 ms |
| 成功中位耗时 | 27509.4 ms |
| 成功 P95 | 40399.6 ms |
| HTTP 200 time_to_headers 平均 | 31727.5 ms |
| HTTP 200 time_to_headers P95 | 42006.3 ms |

失败类型：

| 失败类型 | 次数 | 说明 |
| --- | ---: | --- |
| `ValidationError` | 31 | LLM 返回了 JSON，但不符合 `TravelRequest` schema。最常见问题是 `time_window_start/time_window_end` 输出为 `"08:00"`、`"12:00"` 等字符串，而 schema 期望 TimePoint 对象；另有 `soft_preferences.prefer_rail` 等额外字段。 |
| `ReadTimeout` | 12 | 等到 45 秒 timeout 仍未拿到完整响应。 |
| `RemoteProtocolError` | 4 | 远端在未发送响应时断开连接。 |

关键观察：

- `body_read_ms` 通常接近 0，主要耗时集中在 `time_to_headers_ms`，说明慢点主要发生在远端排队/生成/返回响应头之前，而不是本地读取响应体。
- 即使成功样本也需要 27.1-41.8 秒，不满足实时意图解析要求。
- 当前 prompt 对时间窗口的描述容易诱导模型输出字符串，但 schema 需要对象；这是稳定的结构化输出问题，不只是性能问题。
- 当前 `glm-5.2 + 当前 prompt + response_format + 无 max_tokens` 组合作为在线 intent parser 基线不可接受。
- 2026-07-07 架构决策：Intent Parser Prompt 不再依赖“模型理解 TravelRequest Schema V1.15”这一抽象要求，而是提供最小字段契约、TimePoint 对象格式和关键枚举；完整校验仍由后端 Schema Validator / Semantic Validator 执行。

### 2026-07-06 模型切换后 10 次压测

- 触发原因：用户将 `.env` 中 `REAL_LLM_MODEL` 从 `glm-5.2` 修改为 `glm-4.7-flash`，要求重做 10 次测试并与基线对比。
- 测试命令：
  - `.\.venv\Scripts\python .\scripts\benchmark_intent_llm_latency.py --runs 10 --label model_glm_4_7_flash_10`
- 测试日志：
  - `logs/intent_llm_perf_20260706-230340_model_glm_4_7_flash_10.jsonl`
  - `logs/intent_llm_perf_20260706-230340_model_glm_4_7_flash_10_summary.json`
- 测试配置：
  - model：`glm-4.7-flash`
  - base_url host：`open.bigmodel.cn`
  - timeout：45 秒
  - `response_format={"type":"json_object"}`：启用
  - `max_tokens`：未设置
  - system prompt：2761 字符
  - user prompt：273 字符
  - request body：4730 bytes
  - raw input：26 字符

结果汇总：

| 指标 | `glm-5.2` 基线 50 次 | `glm-4.7-flash` 10 次 |
| --- | ---: | ---: |
| 总次数 | 50 | 10 |
| 成功次数 | 3 | 0 |
| 成功率 | 6% | 0% |
| 全量平均耗时 | 35123.6 ms | 13718.9 ms |
| 全量中位耗时 | 33303.2 ms | 1042.7 ms |
| 全量 P90 | 45060.3 ms | 45006.5 ms |
| 全量 P95 | 46285.7 ms | 45009.1 ms |
| 全量最小耗时 | 13946.1 ms | 205.7 ms |
| 全量最大耗时 | 47018.8 ms | 45011.8 ms |

`glm-4.7-flash` 失败类型：

| 失败类型 | 次数 | 说明 |
| --- | ---: | --- |
| `HTTPStatusError` / 429 | 7 | 接口返回 Too Many Requests。说明当前模型或账号在该调用方式下触发限流，快速失败拉低了中位耗时，但不是有效解析成功。 |
| `ReadTimeout` | 2 | 等到 45 秒 timeout 仍未拿到完整响应。 |
| `ValidationError` | 1 | 唯一一次 HTTP 200 约 42.5 秒后返回，但 `time_window_start/time_window_end` 仍为字符串，不符合 schema。 |

对比结论：

- `glm-4.7-flash` 本轮没有产生成功样本，不能证明它已经解决 intent parse。
- 中位耗时从 33.3 秒降到 1.0 秒，主要是因为 7 次 429 快速失败，不是因为解析成功变快。
- 仍有 2 次 45 秒 timeout，说明模型切换没有消除长尾等待。
- 唯一一次 HTTP 200 仍耗时 42.5 秒且 schema 非法，说明当前 prompt/schema 输出问题依旧存在。
- 下一步若继续验证 `glm-4.7-flash`，应降低并发压力或拉大请求间隔，例如 `--sleep-seconds 3` 或更长，并同时测试关闭 `response_format`、增加 `max_tokens` 的组合。

## 初步判断

50 次基线测试后，结论已经明确：

- 问题不是“用户输入一句话复杂”，而是当前 LLM 调用组合的端到端延迟和输出稳定性都不满足在线解析需求。
- 单独降低 timeout 只能止损，不能解决成功请求仍需 27-42 秒的问题。
- 优先级应从“后台化解析”转向“LLM 解析专项瘦身和供应商/模型验证”。
- `response_format`、prompt、schema 示例和模型选择必须做 A/B 测试，不能直接假设任一单点就是根因。

## 后续任务

- 已完成 50 次基线压测并写回本文。
- 下一步建议按以下顺序做 A/B 测试：
  1. 当前 prompt + 关闭 `response_format`，50 次。
  2. 当前 prompt + `max_tokens=800`，50 次。
  3. 精简 intent prompt + `response_format` + `max_tokens=800`，50 次。
  4. 修正 prompt 中 `time_window_start/time_window_end` 的对象示例，50 次。
  5. 用低延迟 intent 模型替代 `glm-5.2`，50 次。
- 若 A/B 结果仍无法把 P95 控制在 3-5 秒内，应将 LLM intent parser 从主路径移除，改为规则解析主路径 + LLM 辅助解释或追问。
- Recommendation Prompt 同步遵循最小输入原则：只传合法 `plan_id` 清单、候选摘要和输出自检规则，不传完整 `TravelPlan` 或完整 Schema，避免 token 膨胀和模型照抄占位符。

## 2026-07-26 最后一次真机规划链路复盘

### 样本范围

- 请求：`req_80b732447702`
- 异步任务：`job_f9de40d1d515`
- 路线：上海东方明珠塔至北京天安门，出发日期 2026-07-27。
- 证据：
  - `logs/backend-20260726-090338.log`
  - `logs/travel_planner.sqlite3`
- 最终结果：`COMPLETE`，6 个完整门到门方案，其中 4 个铁路方案、2 个航班方案。
- 本节只有一个真机样本，适合做根因定位，不可直接视为 P50/P95。

### 端到端耗时

| 阶段 | 服务端时间 | 阶段耗时 | 结论 |
| --- | --- | ---: | --- |
| 客户端提交开始（由 job 创建时间减去 POST 耗时反推） | 09:05:13.180 | - | 反推值 |
| Intent LLM 完成 | 09:05:17.378 | 3.336 秒 | 本次已不是首要瓶颈 |
| `POST /api/travel/plan/async` 返回并创建 job | 09:05:17.380 | 4.200 秒 | 除 LLM 外约 0.864 秒 |
| 12306 返回 54 个 offer | 约 09:05:19 | job 后约 2 秒 | 干线铁路事实返回较快 |
| 海航返回 2 个可用 offer | 约 09:05:23 | job 后约 6 秒 | 干线航班事实也不是主瓶颈 |
| 首批 3 个铁路完整计划形成 | 约 09:05:38 | job 后约 21 秒 | 被首末程多方式接驳阻塞 |
| 第 4 个铁路计划形成并发布 `RAIL_READY` | 约 09:05:47 | job 后约 30 秒 | 首个渐进快照直到整个铁路 family 完成才发布 |
| `FLIGHT_READY`，共 6 个计划 | 约 09:05:48 | job 后约 31 秒 | 候选集合基本可用 |
| Recommendation LLM 完成 | 09:05:53.106 | 3.567 秒 | 只阻塞最终推荐，不阻塞渐进计划 |
| 服务端终态持久化 | 09:05:53.108 | job 35.728 秒；提交后 39.928 秒 | `COMPLETE` |
| 客户端轮询看到首个渐进结果 | 约 09:05:51 | 提交后约 37.8 秒 | 发布后最多再等当前 5 秒轮询间隔 |
| 客户端轮询看到终态 | 约 09:05:56 | 提交后约 42.8 秒 | 服务端完成后再增加约 2.9 秒 |

### 外部请求扇出

| 调用族 | 次数 | 响应时间窗口 | 观察 |
| --- | ---: | --- | --- |
| 高德路线 driving | 5 | 09:05:21-09:05:41 | 5 个唯一 OD |
| 高德路线 transit | 10 | 09:05:23-09:05:46 | 5 个唯一 OD 被地铁、公交各请求一次 |
| 高德路线 walking | 5 | 09:05:27-09:05:48 | 本样本均为机场或明显超出步行阈值的长距离 |
| 高德地理编码 | 1 | 09:05:30 | 其余地点由目录或缓存解析 |
| 12306 | 2 | 09:05:18-09:05:19 | init + query |
| 春秋航空 | 1 | 09:05:20 | 空结果 |
| 海航 | 5 | 09:05:20-09:05:23 | 得到 2 个 offer |
| 青岛航空 | 8 | 09:05:23-09:05:30 | 后续 scope 重复返回验证挑战 |
| LLM | 2 | 09:05:17、09:05:53 | Intent + Recommendation |

高德路线配置为 `QPS=1`。20 次路线请求从首个响应到最后一个响应持续约 27 秒，控制了本次规划的关键路径。当前规划内缓存已经复用了相同站点和机场的重复路线，但缓存 key 包含 `mode`，所以使用同一 `transit/integrated` 请求参数的地铁与公交仍会产生两次网络调用。

### 当前主要瓶颈

1. `build_local_transfer_options()` 依次查询打车、地铁、公交、步行，只有四种方式全部处理完才返回一个接驳段。
2. 初始方案默认选择打车，但系统仍先等待未选中的地铁、公交、步行，导致“完整且安全的首个计划”被备选接驳阻塞。
3. 步行会先请求地图，再在机场接驳或距离超过 2200 米时丢弃；可在请求前用已知场景和直线距离下界安全短路。
4. 地铁和公交在高德适配器上使用相同的综合公交请求，但规划缓存按两个 mode 分开。
5. `PlanningProgressSink` 当前在一个 Provider family 的 future 整体完成后发布；首批 3 个铁路计划已在约 21 秒形成，却等到第 4 个计划约 30 秒时才发布。
6. 青岛航空出现“请验证”后仍继续其余机场 scope，增加无效请求和 Provider family 尾延迟。
7. 前端活动态退避上限为 5 秒，使首个方案和终态各增加 0-5 秒可见延迟。
8. 每 job 的阶段耗时和缓存计数只存在进程内聚合指标，重启后无法按 request/job 精确复盘。

## 下一轮链路优化方案

### P0：先把首个安全方案提前

1. 将接驳构建拆成“选中方式验证”和“备选方式补齐”两阶段。
2. 第一阶段只查询当前选中方式；初始规划仍使用现有默认打车，不生成规则估算。
3. 首末程选中方式均验证成功后立即形成完整门到门计划，通过现有候选安全门禁后发布渐进快照。
4. 第二阶段再补齐地铁、公交和步行，并以相同 `plan_id` 更新计划快照；当前选中方式与价格、耗时语义保持稳定。
5. 增加线程安全的渐进候选协调器，使单个计划形成后即可发布，不再等待整个铁路或航班 family 返回。
6. 地图调度优先级固定为：首个候选的选中接驳 > 其他候选的选中接驳 > 备选接驳。所有调用继续服从现有 QPS。

### P1：减少冷缓存地图请求

1. 高德综合公交按 `OD + provider + city` 只请求一次，再从同一响应中分别投影地铁和公交选项。
2. 步行请求前执行安全短路：
   - 机场接驳不请求步行；
   - 坐标直线距离已经超过 2200 米时，不请求步行；
   - 短路表示“不适用”，不得记录为 Provider 失败。
3. 以本样本 5 个唯一 OD 估算，冷缓存路线网络调用可从 20 次降至约 10 次：5 次 driving + 5 次 transit；实际结果必须由 benchmark 验证。
4. 若仍不达标，再增加跨 job 短 TTL 路线缓存和 single-flight；key 必须包含 Provider、坐标、mode/query family、城市和环境，动态路线不得使用过长 TTL。

### P1：缩短航班 Provider 尾部

1. 青岛航空一旦返回明确验证挑战，在当前 job 内打开 Provider 级熔断，停止剩余机场 scope。
2. 不把挑战响应当作 `EMPTY`，保留稳定 source failure。
3. 不提高单 Provider QPS；若后续并行不同航司，必须保证独立会话、独立限流和有界 worker。

### P1：缩短客户端可见延迟

1. 在 `plans=[]` 的活动态，将轮询退避上限从 5 秒收紧到 2 秒并保留抖动。
2. 首个计划可见后可恢复较慢轮询，降低服务压力。
3. 若生产并发上升后轮询压力不可接受，再设计基于 `updated_at` 的长轮询；本轮不直接引入 SSE/WebSocket。

### P0：补齐可验证观测与配置一致性

1. 每个 job 输出一条脱敏结构化 summary，至少包含：
   - `intent_parse_ms`
   - `rail_core_ms`
   - `flight_core_ms`
   - `first_plan_built_ms`
   - `first_snapshot_ms`
   - `transfer_hydration_ms`
   - `recommendation_ms`
   - `final_result_ms`
   - 各 Provider 请求数、挑战/失败数、路线和地点缓存命中/未命中数
2. summary 只记录 request/job 标识和计数，不记录完整地点、用户输入、票务会话或密钥。
3. 当前 `.env` 仍覆盖 `TRAVEL_ASYNC_JOB_TIMEOUT_SECONDS=30`，而代码和 `.env.example` 默认 180 秒。强制模式启用前必须移除漂移或恢复 180 秒；在完成足够样本前继续使用 `observe`。
4. HTTP 客户端日志当前会输出带 query credential 的完整 URL。必须先增加日志脱敏并轮换已暴露凭据；该项是安全修复，不计入延迟收益。

### 目标预算

以下是下一轮验收目标，不是当前实测结果：

| 指标 | 当前单样本 | 下一轮冷缓存目标 |
| --- | ---: | ---: |
| Intent parse | 4.2 秒（接口阶段） | P95 ≤ 4 秒 |
| 服务端首个可用计划 | 约 30 秒 | P95 ≤ 12 秒 |
| 客户端首个计划可见 | 约 37.8 秒（含 Intent） | P95 ≤ 14 秒 |
| 服务端最终结果 | 35.7 秒（job） | P95 ≤ 25 秒 |
| 客户端发布感知附加耗时 | 0-5 秒 | P95 ≤ 2 秒 |
| 本样本冷缓存高德路线调用 | 20 次 | ≤ 10 次 |

### 验证方法

- 冷缓存与暖缓存分别至少 30 次。
- 路线至少覆盖：
  - 单一铁路可用；
  - 铁路与航班同时可用；
  - 航司出现挑战；
  - 地图单方式失败但其他方式可用；
  - 无完整方案。
- 输出 P50/P95/P99、首个方案与最终结果差值、Provider 请求计数和缓存命中率。
- 验证渐进快照中的每个计划都通过现有完整性、安全和可推荐性门禁。
- 不以提高高德或航司 QPS、不恢复规则估算、不减少最终数据真实性来换取耗时。
