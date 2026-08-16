# 开发任务：自然语言相对日期与时间解析

> 来源：`docs/ARCHITECTURE.md`“自然语言相对日期与时间解析（已批准目标）”。
> 创建日期：2026-08-14。
> 更新日期：2026-08-16；补充真机 HTTP 400 复现与“立即出发”P0 修复范围。
> 完成状态：已完成（2026-08-16 18:38 +08:00）；核心代码提交 `a7df17f`。

## 目标

- 修复自然语言输入包含有效日期语义、但 LLM 输出格式非法时被误报为 `PARSE_NEEDS_INPUT` 的问题。
- 支持常见相对日期与时间表达，并以 `Asia/Shanghai` 的后端权威时钟确定性归一化。
- 对真正歧义的表达给出具体追问，不静默猜测，不只显示笼统“自然语言解析失败”。
- 不修改 V1.18 Schema，不新增数据库字段。

## 当前问题与复现

- `backend/app/services/intent_parser.py::_extract_date` 当前只覆盖今天、明天、后天、明确年月日和有限月日格式。
- `OpenAICompatibleLLMProvider.parse_intent()` 只提供 `current_date`，未提供带时区的 `current_datetime`。
- Intent prompt 没有明确要求 `travel_date` 必须为 `YYYY-MM-DD`；repair 后仍可能触发 `travel_date: Input should be a valid date`。
- LLM 与 repair 都失败后虽会进入规则兜底，但“下周六”等表达仍无法恢复。
- 已复现输入（地点脱敏）：“我现在就要从上海市南翔镇某小区出发，到杭州市”。首次 LLM 与 repair 均返回非法 `travel_date`，`POST /api/travel/parse` 与 `POST /api/travel/plan/async` 均返回 HTTP 400；后者未创建 `job_id`。
- 同一运行环境使用“今天18点后从上海市南翔镇某小区出发，到杭州市”可得到合法 `travel_date` 和 `TimePoint`，证明故障位于“现在”语义与日期归一化，不是端口、Provider 配置或地点结构问题。

## P0-1：建立权威时间上下文

涉及文件：

- `backend/app/services/intent_parser.py`
- `backend/app/data_sources/llm_providers.py`
- 对应模型接口与测试 fake

任务：

- 使用 `datetime.now(ZoneInfo("Asia/Shanghai"))` 或可注入的等价 clock 生成解析基准，禁止依赖裸 `date.today()` 和服务器默认时区。
- 每个解析请求只捕获一次 `current_datetime`，首次解析、repair、确定性兜底和最终字段生成必须复用同一快照，避免秒级漂移或跨午夜产生两个日期。
- 将带偏移的 `current_datetime` 和 `default_timezone=Asia/Shanghai` 传入首次 Intent prompt 与 repair prompt。
- 允许测试注入固定当前时刻，禁止通过 monkeypatch 全局系统时钟制造脆弱测试。
- 客户端时间只可作为诊断信息，不得成为权威计算输入。

验收：固定 `2026-08-14T23:15:00+08:00` 时，首次解析与 repair 收到完全一致的权威时间上下文。

## P0-2：实现确定性相对日期解析

涉及文件：

- `backend/app/services/intent_parser.py`
- 可按职责新增 `backend/app/services/relative_datetime_parser.py`

任务：

- 保留今天、明天、后天和现有明确日期行为。
- 新增本周几/这周几、下周几/下星期几、最近的周几，支持“周一～周日”“星期一～星期天/日”。
- 明确一周按周一开始；“下周几”落入紧随当前周的下一自然周。
- “最近的周几”选择严格不早于当前时刻的最近目标星期；若产品要求当天已过可用时间则进入下一周，规则必须可测试。
- 新增“N 小时后”，基于权威 `current_datetime` 生成首选出发 `TimePoint`，跨午夜时同步更新 `travel_date`。
- 新增与出发动作绑定的立即出发词组：至少覆盖“现在就要出发”“现在出发”“马上出发”“立即出发”“即刻出发”“尽快出发”，允许地点成分插入“现在就要从 A 出发”的自然句式。
- 立即出发统一生成 `travel_date=current_datetime.date()`、`time_anchor_type=DEPARTURE`、`earliest_departure_time=current_datetime`、`time_window_start=current_datetime`、`time_window_end=null`；两个 TimePoint 必须来自同一快照且带 `+08:00`、`Asia/Shanghai`。
- 不能对任意“现在”做字符串替换：“我现在想规划明天出发”必须保留明天；“现在就要出发”同时出现明确未来日期/时间时，按明确合同优先级消歧，无法消歧则返回具体追问，不得随机覆盖。
- 可选扩展“N 天后”；不得在本任务中无边界扩展所有中文时间表达。
- 所有成功结果统一为 `travel_date: YYYY-MM-DD` 和带时区 `TimePoint`。

验收：以 2026-08-14（周五）为基准，“下周一”得到 2026-08-17，“下周六”得到 2026-08-22；23:15 的“三小时后”得到 2026-08-15T02:15:00+08:00。固定 `2026-08-16T16:57:38+08:00` 时，脱敏复现句必须得到 `travel_date=2026-08-16`，且 `earliest_departure_time` 与 `time_window_start` 均为 `2026-08-16T16:57:38+08:00`。

## P0-3：定义歧义与过去日期行为

任务：

- “这个周末”在用户没有指定周六/周日时不得默认选一天；返回针对性问题“周六还是周日出发？”。
- “月底”在产品合同仍只允许单个 `travel_date` 时不得默认最后一天；返回针对性具体日期追问。
- “周六”等没有本周/下周/最近限定的表达，采用产品明确规则或追问；不得由 LLM 每次随机决定。
- 解析到昨天或其他过去日期时，返回独立、可解释的过去日期校验信息，不调用地图或票务 Provider。
- `missing_fields`、`follow_up_questions` 与 `user_visible_message` 保持一致；前端不得只显示通用错误标题。

验收：歧义表达稳定进入 follow-up，过去日期稳定被阻断，均不产生规划异步任务。

## P0-4：强化 LLM 输出与 repair

涉及文件：

- `backend/app/llm/prompts/intent_parser_prompt_v1_0.txt`
- `backend/app/llm/prompts/repair_prompt_v1_0.txt`
- `backend/app/data_sources/llm_providers.py`

任务：

- 明确 `travel_date` 只能为 `YYYY-MM-DD` 或在信息确实缺失/歧义时为 `null`。
- Intent prompt 必须明确“现在就要从 A 出发”等立即出发语义可由 `current_datetime` 确定，不属于缺失日期；最小 JSON 示例不得诱导模型对可确定的相对日期输出 `null`。
- 提供相对日期规范化示例，但动态日期必须由传入的 `current_datetime` 计算，禁止写死示例日期成为运行事实。
- repair prompt 必须携带原始输入、权威当前时刻、原始输出和具体校验错误。
- LLM 输出格式错误时，优先用原始输入的确定性结果修复；不得采信 LLM 对明确用户事实的改写。
- 日志继续只记录 hash、模型、耗时和错误原因，不记录完整用户输入、Prompt 或输出。

验收：真实 LLM 返回中文日期、完整 datetime 或 null 等非法 `travel_date` 时，只要原始输入可确定，仍能形成合法 `TravelRequest`；LLM 和 repair 都失败时，脱敏复现句也不得返回 400。

## P1：前端追问体验

涉及文件：

- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- 输入页相关组件

任务：

- 展示后端 `user_visible_message` 和首个 `details.follow_up_questions`，不能只显示“自然语言解析失败”。
- 保留用户原始输入，允许补充日期后再次提交。
- 解析错误不进入规划 loading，不创建轮询任务；重复提交保护保持生效。

验收：用户输入“这个周末从上海到武汉”时看到具体日期追问，补充后可正常提交。

## 影响与非目标

- 影响：自然语言解析、错误提示和相关测试；同步/异步规划的结构化输入路径不变。
- 无 API 字段变更、无 schema version 升级、无数据库迁移。
- 非目标：支持农历、节假日调休、复杂多段日期范围、返程日期和国际时区自然语言。
- 非目标：让 LLM 成为时间计算的唯一权威来源。

## 验收与回归

- 完成 `docs/Test/task_from_arc_for_test_20260814_relative_datetime.md` 的全部用例。
- 执行：
  - `python -m pytest backend/app/tests/test_api.py`
  - 相对时间解析专项测试文件（如新增）
  - `python -m pytest backend/app/tests`
  - `npm run typecheck`（`frontend/`）
  - `npm run test:helpers`（`frontend/`）
- 至少完成一次真实 LLM parse smoke，确认明确日期与“下周六”均返回合法 `TravelRequest`。
- 使用脱敏复现句完成 `/api/travel/parse` 与 `/api/travel/plan/async` 回归；parse 必须成功，async 必须创建 `job_id`，且解析阶段不得因 `travel_date` 返回 400。

## 风险与回滚

- 周边界、跨月/跨年和跨午夜最易出现 off-by-one，必须使用固定时钟测试。
- 功能开关关闭时回到现有解析路径；保留明确日期和今天/明天/后天已有行为。
- 回滚不得修改 V1.18 请求/响应结构，也不得放宽过去日期与时区校验。

## 完成记录

- P0：新增独立确定性解析器，覆盖明确日期、今天/明天/后天、本周/下周/最近星期、N 小时后、立即出发、歧义追问和过去日期阻断；每个请求只捕获一次上海权威时刻。
- LLM：首次与 repair prompt 复用相同 `current_datetime` 和 `default_timezone`；后端用原始输入的确定性事实覆盖非法或非规范 `travel_date`。
- P1：前端保留结构化 API 错误与首个具体追问；异步 job 创建成功前停留在输入页，解析失败保留原始输入并回到输入页。
- 数据库与合同：无迁移、无字段变更、Schema 继续为 V1.18。
- 验证：后端全量 pytest、前端 typecheck/helper tests、Expo 三平台导出、真实 `glm-4.5-air` 明确日期与“下周六” smoke 均通过。
