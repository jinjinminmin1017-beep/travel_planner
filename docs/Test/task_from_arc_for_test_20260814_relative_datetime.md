# 测试任务：自然语言相对日期与时间解析

> 对应开发任务：`docs/Dev/task_from_arc_for_dev_20260814_relative_datetime.md`。
> 更新日期：2026-08-16；补充“立即出发”生产式回归。
> 执行状态：已完成（2026-08-16）；自动化与真实 LLM smoke 均通过，核心代码提交 `a7df17f`。

## 测试原则

- 所有相对日期测试注入固定 `Asia/Shanghai` 当前时刻，不依赖执行测试当天的系统时间。
- 单元测试使用 fake LLM；真实 LLM 仅用于显式 opt-in smoke。
- 分开验证语义识别、确定性归一化、Schema 校验、API 错误和前端展示。

## P0-1：明确日期与既有规则回归

- `2026年8月20日`、`2026-08-20`、`8月20日` 均归一化为 `2026-08-20`。
- 今天、明天、后天相对固定时钟正确计算。
- 月日跨年：当前日期之后使用本年，已经过去则按既有合同落到下一年。
- 明确非法日期（如 2 月 30 日）返回可解释错误，不抛出未处理异常。

## P0-2：星期表达

固定当前时刻：`2026-08-14T10:00:00+08:00`（周五）。

- 下周一/下星期一 -> `2026-08-17`。
- 下周六/下星期六 -> `2026-08-22`。
- 下周日/下星期天 -> `2026-08-23`。
- 本周六/这周六 -> `2026-08-15`。
- 最近的周六 -> `2026-08-15`。
- 周一到周日、星期一到星期天/日的别名映射完整。
- 当前日、周末、月末、年末边界无 off-by-one。

## P0-3：立即出发语义

固定当前时刻：`2026-08-16T16:57:38+08:00`。

- “我现在就要从上海市南翔镇某小区出发，到杭州市”解析为 `travel_date=2026-08-16`、`time_anchor_type=DEPARTURE`。
- `earliest_departure_time` 与 `time_window_start` 必须完全相同，均为 `2026-08-16T16:57:38+08:00`；`time_window_end=null`，timezone/source_timezone 均为 `Asia/Shanghai`。
- “现在出发、马上出发、立即出发、即刻出发、尽快出发”覆盖同一确定性语义；地点插入词组中间不影响识别。
- “我现在想规划明天出发”仍解析为 `2026-08-17`，不得因出现“现在”覆盖明确日期。
- 立即出发表达与明确未来日期/时间冲突时，结果遵守唯一确定的优先级或返回具体 `PARSE_NEEDS_INPUT`，不得随 LLM 输出变化。
- fake LLM 分别返回 `travel_date=null`、`travel_date="现在"`、完整 datetime 和非法日期，repair 也失败时仍从原文恢复合法请求。
- `/api/travel/parse` 必须返回 200；`/api/travel/plan/async` 必须创建 `job_id`，不得在解析阶段返回 400。规划端到端测试使用 fake Provider，不能依赖真实票务或地图服务。

## P0-4：相对小时与跨午夜

- 固定 `2026-08-14T10:00:00+08:00`，“三小时后”得到当天 13:00。
- 固定 `2026-08-14T23:15:00+08:00`，“三小时后”得到 `2026-08-15T02:15:00+08:00`，且 `travel_date=2026-08-15`。
- 跨月、跨年场景同步更新日期。
- 输出 `TimePoint.datetime` 包含 `+08:00`，timezone/source_timezone 均为 `Asia/Shanghai`。
- “三小时后到达”和“三小时后出发”分别映射到正确时间锚点。

## P0-5：歧义与过去日期

- “这个周末”没有指定周六/周日时返回 `PARSE_NEEDS_INPUT` 和“周六还是周日”追问。
- “月底”没有具体日期时返回针对性追问，不静默选择最后一天。
- 无限定“周六”按最终产品规则稳定处理或稳定追问，不随 LLM 输出变化。
- 昨天和明确过去日期返回过去日期错误，不调用规划器或任何票务/地图 Provider。
- 真正没有日期的输入继续返回缺少 `travel_date`，不得伪造日期。

## P0-6：LLM 与确定性兜底

- LLM 返回合法 `YYYY-MM-DD` 时直接通过。
- LLM 返回中文日期、完整 datetime、null、错误字段名和非法 JSON 时触发 repair/兜底。
- 原始输入日期可确定时，即使 LLM 与 repair 都格式错误，也由后端恢复合法请求。
- 原始输入包含与出发动作绑定的立即出发语义时，属于可确定日期/时间，不得归类为缺少 `travel_date`。
- 原始输入确实歧义时，repair 不得猜日期。
- 首次 prompt 和 repair prompt 都包含相同的 `current_datetime` 与 `Asia/Shanghai`。
- 日志不包含完整原始输入、Prompt、LLM 输出或密钥。

## P0-7：API 与前端

- `/api/travel/parse`、`/api/travel/plan`、`/api/travel/plan/async` 对相同文本采用一致解析语义。
- 解析成功响应中的 `travel_date` 与 TimePoint 合同不变。
- 歧义错误返回 HTTP 400、`PARSE_NEEDS_INPUT`、正确 `missing_fields` 和具体 `follow_up_questions`。
- 解析失败不创建 async job，不调用 Provider。
- 前端显示服务端具体追问并保留输入；不得只显示通用“自然语言解析失败”。

## 回归命令与通过标准

- `python -m pytest backend/app/tests/test_api.py`
- 相对日期时间专项测试文件（如新增）
- `python -m pytest backend/app/tests`
- `npm run typecheck`（`frontend/`）
- `npm run test:helpers`（`frontend/`）
- 所有新增与既有用例通过；固定时钟下结果稳定，测试日期变化不影响断言。

## 执行结果

- 相对日期时间专项：49 passed。
- 后端全量：351 passed。
- 前端：TypeScript 检查通过，helper/UI tests 28 passed，Web/iOS/Android Expo 导出通过。
- API：脱敏立即出发句的 `/api/travel/parse`、`/api/travel/plan`、`/api/travel/plan/async` 回归通过，async 成功创建 `job_id`；歧义日期不创建 job。
- 真实 LLM：`glm-4.5-air` 的明确日期与“下周六”均为 `USE_ORIGINAL`，分别归一化为 `2027-08-20` 与 `2026-08-22`。
