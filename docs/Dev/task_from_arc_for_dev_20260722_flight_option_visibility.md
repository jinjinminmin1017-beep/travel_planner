# ARC-20260722-01 航班选项可见性与交通方式覆盖语义

来源：用户反馈“最后一次规划结果没有看到航班选项”，架构核查日期 2026-07-22。

状态：待开发。

## 1. 已确认现状

- 最后一次持久化规划为上海静安寺到温州永嘉，返回 4 个铁路计划、0 个航班计划。
- 航班查询实际执行：春秋 429、海航空结果、青岛航空业务响应未通过校验；没有可验证 `FlightOffer`。
- 东航 browser source 仍未通过 50 次稳定性和许可门禁，必须保持禁用。
- 响应包含航班 `blocked_plan_types`、`missing_plan_explanations`、`source_failures`，但结果页没有交通方式层，只显示实际计划和推荐目标。
- 响应错误地使用 `planning_status=COMPLETE`；前端类型还缺少 `missing_plan_explanations`。

## 2. 目标

1. 有真实航班计划时，用户可以通过“航班”入口查看并选择。
2. 没有真实航班计划时，仍明确显示航班状态和原因，但不生成占位计划。
3. 查询失败、限流、超时与确认空结果具有不同语义。
4. 查询范围内航班核心事实不可用时，铁路结果继续可用，但整体状态为 `PARTIAL`。
5. 不改变 V1.17 外部字段，不进行数据库迁移，不绕过任何航司门禁。

## 3. 后端任务

### 3.1 Provider outcome 结构化

- 在航班 Provider 聚合层新增内部 attempt/outcome 模型，至少包含：
  - `source_id`
  - `status`: `VERIFIED | EMPTY | RATE_LIMITED | TIMEOUT | FAILED | DISABLED`
  - `error_code`
  - `retryable`
  - `offer_count`
  - 脱敏 `message`
- `search_flight_offers_with_enabled_provider_result()` 不再只返回 `attempted_source_ids + failure_message`。
- 每个失败来源生成独立 `SourceFailure`；禁止把所有错误拼接后挂到最后一个 source_id。
- `FLIGHT_PROVIDER_EMPTY` 只用于成功空结果；429 使用 `FLIGHT_PROVIDER_RATE_LIMITED`，超时、挑战和非法业务响应分别使用稳定错误码。
- 保持“任一来源返回真实 offer 即可继续生成计划”，同时保留其他失败来源供覆盖状态与 UI 说明使用。

### 3.2 规划状态

- 在 `planner.py` 计算本次 in-scope 交通方式：
  - 有 `allowed_transport_modes` 时按其范围。
  - 移除 `excluded_transport_modes`。
  - 默认城际路线在站点与机场可解析时包含 `RAIL`、`FLIGHT`。
- 若 in-scope 航班无计划且存在失败、限流或超时，其他铁路计划可返回，但 `planning_status=PARTIAL`。
- 若航班被用户显式排除或路线无适用机场，不因航班缺失降级。
- 所有相关航班来源成功空结果时，保留准确“未找到”说明；不得与系统失败混用。
- 保持现有 `NO_MATCH`、安全门禁、推荐资格和无虚构事实规则。

## 4. 前端任务

### 4.1 类型同步

- 在 `frontend/src/types/index.ts` 增加 `MissingPlanExplanation`。
- 在 `TravelPlanResponse` 增加 `missing_plan_explanations: MissingPlanExplanation[]`。
- 与后端 schema/导出 JSON 做合同对照，禁止使用 `any` 绕过。

### 4.2 交通方式入口

- 在结果概览“选择方案”区域增加独立 `TransportModeSelector`，至少展示铁路、航班。
- `PlanSelector` 继续只显示综合推荐、更舒适、更省预算，不把交通方式塞入推荐槽。
- 状态推导：
  - 有包含对应干线 segment 的真实计划：可用。
  - 没有真实计划但属于查询范围：显示“未找到”或“暂不可用”。
  - 用户显式排除：隐藏，或显示“未纳入本次规划”；不得显示失败。
- 点击可用方式后，只展示该方式真实候选；不能合成 plan_id 或航班事实。
- 点击不可用航班后显示原因、来源状态和可用动作，不进入路线详情、重算或预订。
- 失败可触发既有 `retryPlanningJob()`；重试期间保留铁路结果并禁用重复提交。
- redirect-only 官方查询如保留，必须显示“离开应用查询，非本次已验证方案”。

## 5. 目标文件

- `backend/app/data_sources/flight_providers.py`
- `backend/app/services/planner.py`
- `backend/app/models/schemas.py`（仅内部模型确有必要时；不得擅自改外部 V1.17 字段）
- `frontend/src/types/index.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/results/ResultsOverview.tsx`
- `frontend/src/components/results/TransportModeSelector.tsx`（新增）
- `frontend/src/components/results/PlanSelector.tsx`（仅保持职责边界所需调整）
- 对应后端、前端与合同测试

## 6. 验收标准

- 最后一次问题响应的等价 fixture 显示：铁路可用、航班暂不可用、准确原因、可重试；整体为 `PARTIAL`。
- 有真实航班计划时，航班入口可用，选择后展示真实航班号、机场、时刻、舱位和价格。
- 推荐槽即使全部指向铁路，航班真实候选仍可通过交通方式入口访问。
- 航班失败时 UI 不出现虚构航班卡、价格、时刻、plan_id 或预订按钮。
- 显式排除航班的请求不显示航班失败，不因航班缺失降为 `PARTIAL`。
- 单一来源 429、空结果、超时和非法响应分别生成正确 source_id 与错误码。
- 旧 V1.17 聚合失败响应使用保守“暂不可确认”兼容展示。

## 7. 建议验证命令

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_planning_rules.py backend/app/tests/test_api.py -q
npm --prefix frontend test
npm --prefix frontend run typecheck
git diff --check
```

## 8. 风险与回滚

- 用独立前端功能开关控制交通方式入口；关闭后恢复现有结果页。
- Provider outcome 重构可单独回滚，但不得恢复混淆空结果和失败的错误码。
- 东航 source 继续遵守原 ARC-20260719-01 门禁，本任务不得顺带启用。
