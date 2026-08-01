# ARC-20260801-03 预算方案席别物化与推荐确定性门禁

来源：用户复核 `req_a39683871cca` 时发现“更省预算”选择一等座。架构依据见 `docs/ARCHITECTURE.md`“航班自适应限流与预算方案选项物化架构”中的预算方案部分；航班限流、缓存、交换证据和 Provider 调整不属于本轮开发范围。

状态：已完成。完成时间：2026-08-02 07:59:16 +08:00。代码提交：`13a3a55`。

## 已确认事实

- D3291 一等座 ¥418、二等座 ¥262 均为 AVAILABLE；Planner 因席别列表顺序选中一等座，并非二等座无票。
- 当前四个计划按最低价可售席别、保持接驳不变时，总价分别约为 G1673 ¥338、G7591 ¥302.50、G7511 ¥340、D3291 ¥326。
- 当前“更省预算”返回 D3291 ¥482；正确的结果集最低价应为 G7591 ¥302.50。
- 推荐阶段当前只验证 LLM 返回的 plan_id 是否属于合法候选，没有验证 CHEAPEST 是否满足确定性最低价语义。

## 开发任务 A：有界铁路席别方案物化

1. 新增职责单一的方案选项物化器；每个基础铁路 itinerary 最多生成 COST_OPTIMIZED、COMFORT_OPTIMIZED、BALANCED 三类变体。
2. 显式 `preferred_rail_seat` 优先；不可用时走现有约束解释，不静默替换。
3. COST_OPTIMIZED 从真实可售铁路席别中选择满足硬约束的最低门到门总价组合。
4. 席别变化后统一重算 cost、comfort、risk，再经过约束与安全门禁。
5. 不做无界组合；按 selected seat fingerprint 去重。
6. 同一基础行程的不同席别组合必须生成不同 plan_id。
7. 修正 `_rail_segment_from_offer()`，禁止继续选择 Provider 顺序中的第一个可售席别。
8. 本轮不修改航班 Provider、航班舱位选择、航班缓存、限流或交换证据链路。

## 开发任务 B：推荐确定性门禁

1. CHEAPEST 按 eligible 变体的 total cost、总时长、plan_id 确定性选择。
2. MOST_COMFORTABLE 按舒适度、风险、成本稳定选择。
3. BALANCED 可继续使用 LLM，但候选必须限制在后端生成的 Pareto 集。
4. 扩展 LLM 语义验证；极值 slot 不匹配时采用确定性结果，而不是接受一个仅格式合法的 plan_id。
5. 推荐理由必须引用实际 selected seat 与重算后的总价。

## 兼容与范围

- API schema 维持 V1.17，不新增外部字段，不做数据库迁移。
- 主要文件：`backend/app/services/planner.py`、建议新增的 `backend/app/services/plan_variant_materializer.py`、`backend/app/services/cost_comfort_risk_engine.py`、`backend/app/services/recommendation.py`。
- 铁路事实继续来自现有 12306 Provider；不得伪造席别、票价或库存。
- 不修改 `flight_providers.py`、`browser_flight_providers.py`、`rate_limiter.py`、航班配置或浏览器 worker。

## 开发验收

- D3291 成本变体选择二等座，总价为 ¥326；明确要求一等座时仍选择一等座。
- 四车次 fixture 的 CHEAPEST 为 G7591 ¥302.50。
- 同一铁路行程不同席别变体具有不同 plan_id，费用和舒适度与 selected seat 一致。
- 推荐卡、详情、费用明细、selected seat 和理由一致。
- 航班相关源文件和配置无 diff。
- 运行后端全量测试与 schema diff 检查。

## 回滚

- 方案物化与推荐确定性门禁使用独立开关。
- 物化器异常时回滚为“未显式指定席别时选择最低价可售席别”的安全基线；不得恢复按 Provider 列表第一个可售席别选择。

## 完成记录

- 新增 `PlanVariantMaterializer`，对每个含铁路段的基础行程仅使用真实 `AVAILABLE/LIMITED` 且有价格的席别，生成最多三个 `COST_OPTIMIZED`、`COMFORT_OPTIMIZED`、`BALANCED` 变体；按 selected option fingerprint 去重并生成独立 `plan_id`。
- 未指定席别时，Planner 安全基线改为确定性最低价可售席别，不再消费 Provider 列表顺序；显式席别可售时只物化该席别，不可售时保留最低价事实供现有约束解释处理，不静默换席。
- 席别变体统一重算费用、总时长、席别舒适度分项和推荐可用风险状态；费用明细、selected seat、总价和舒适度保持一致。
- CHEAPEST 按总价、总时长、`plan_id` 确定性选择；MOST_COMFORTABLE 按舒适度、风险、成本、时长和 `plan_id` 稳定选择；BALANCED 的 LLM 输入限制为后端 Pareto 集。
- 合法但不满足极值语义的 LLM plan_id 会被确定性门禁纠正；推荐理由由实际席别/舱位和门到门总价生成。
- 增加 `TRAVEL_RAIL_PLAN_VARIANTS_ENABLED` 与 `TRAVEL_DETERMINISTIC_RECOMMENDATION_GATE_ENABLED` 两个独立开关；关闭物化器时仍保留最低价可售席别安全基线。
- D3291 fixture 验证二等座成本变体总价为 ¥326，一等座显式偏好仍为 ¥482；四车次 fixture 验证 CHEAPEST 为 G7591 ¥302.50。
- 验证：后端 257 passed；Python compileall、schema export/diff、`git diff --check` 通过；Ruff 未安装，未执行。
- 外部 API schema 保持 V1.17，无数据库迁移；航班 Provider、航班配置、限流与 browser worker 无 diff。
