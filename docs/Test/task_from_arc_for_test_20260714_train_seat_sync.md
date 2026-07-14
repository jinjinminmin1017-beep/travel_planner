# ARC-TEST-20260714-02 同车次席别同步回归测试

来源：`ARC-20260714-02`，2026-07-14。

完成状态：已完成（2026-07-14）。

## 核心场景

1. 构造 A、B 两个方案且均包含 G56，两个段使用不同 option_id；在 A 的 G56 选择一等座后，A/B 分别选中自己的合法一等座 option_id。
2. A 方案同时包含 G56 与 K597；同步后 K597 的 selected_seat_option_id、费用项和席别保持不变。
3. C 方案不包含 G56；同步后 C 的计划快照、推荐资格和费用保持不变。
4. B 包含 G56 但缺少目标席别；B 进入 unsupported_plan_ids，A 正常应用，C 不受影响。
5. 请求中的 option_value 与真实 option_id 对应席别不一致时，以后端 option_id 解析结果为准。
6. 同步前后 TravelRequest.preferred_rail_seat 与 preference_source 保持不变。
7. updated_response、顶层 recommendation_result、持久化 plan 查询和再次重算读取同一快照版本。

## 前端场景

- 席别调整继续发送 RESULT_SET + FULL_REEVALUATION。
- 前端整体替换 updated_response，切换到其他包含同车次的方案时显示已同步席别和各自价格。
- 不同车次保持原席别；提示文案包含目标车次，不使用“全部铁路段”或“全程统一席别”。

## 验收命令

- `python -m pytest backend/app/tests/test_api.py`
- `npm run test:helpers`
- `npm run typecheck`
- `python scripts/export_schemas.py`

## 执行结果

- 同车次跨方案同步与 G834 + K597 不同车次回归：2 passed。
- `backend/app/tests/test_api.py`：47 passed。
- 前端 `npm run typecheck`：通过。
- 前端 `npm run test:helpers`：11 passed。
- Schema 导出：通过，`schemas/` 无差异。
- 后端全量：205 passed、3 failed；失败项均为本机高德地理编码已启用与测试预期默认禁用冲突，涉及 `test_data_sources.py`、`test_geocoding_providers.py`、`test_location_resolver.py`，与席别同步改动无关。
