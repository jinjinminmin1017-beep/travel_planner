# ARC-20260714-02 将结果集席别传播修正为同车次同步

来源：用户业务规则澄清，2026-07-14。

完成状态：已完成。完成时间：2026-07-14。代码提交：`a8c9c91a786e12969eb177926beb1a0df8e92ccd`。

## 背景

当前实现把任一铁路段选择的席别传播到结果集内所有计划的所有铁路段。用户确认正确业务规则是：多个方案包含同一车次（例如 G56）时，在任一方案的 G56 上选择席别，应同步到其他方案的 G56；不同车次不得被同时修改。

## 开发任务

1. 后端从目标段合法 option_id 解析 canonical seat_type，并从目标段读取规范化 train_number。
2. 只遍历和更新结果集中 train_number 相同的铁路段；同一计划中的其他车次保持原席别。
3. 不包含目标车次的计划保持费用、推荐资格和选中席别，不进入 unsupported_plan_ids。
4. 仅当计划包含目标车次但该段缺少目标席别时，才标记 RAIL_SEAT_UNSUPPORTED。
5. 不再改写 TravelRequest.preferred_rail_seat 或 preference_source，避免把车次级选择提升为全行程硬约束。
6. 每个命中计划使用自己的合法 option_id 和价格刷新费用、舒适度与数据质量。
7. 在完整更新后的计划集上重新生成推荐，并原子替换结果集快照。
8. 前端继续消费 updated_response 整体替换状态，成功提示明确包含目标车次，不显示“全程席别已统一”的误导语义。

## 测试要求

- 两个方案都包含 G56：从 A 选择一等座后，A/B 的 G56 都变为一等座。
- 同一方案包含 G56 与 K597：只修改 G56，K597 保持原席别。
- 不包含 G56 的计划保持推荐资格和原价格。
- 同车次计划缺少目标席别时，仅该计划进入 unsupported_plan_ids。
- TravelRequest.preferred_rail_seat 和 preference_source 不因车次级同步改变。
- 伪造 option_value 不影响后端从 option_id 解析的 canonical seat_type。

## 文件范围

- `backend/app/services/result_set_preferences.py`
- `backend/app/services/planner.py`
- `backend/app/tests/test_api.py`
- `frontend/tests/ui-contract.test.mjs`
- `docs/API_CONTRACT.md`
- `docs/ARCHITECTURE.md`

## 验收标准

- 不同车次不再因一次席别切换被改动或退出推荐。
- 同车次跨方案席别、价格、详情和推荐卡保持一致。
- 无数据库迁移，无新增 API 字段，schema version 保持 V1.17。
- 后端相关测试、前端 typecheck、UI contract 测试和 schema export/diff 通过。
