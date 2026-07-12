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
