# TEST-20260722-01 航班选项可见性与覆盖语义验收

来源：`docs/Dev/task_from_arc_for_dev_20260722_flight_option_visibility.md`。

状态：待测试。

## 1. 后端测试

- 春秋 429、海航空、青岛航空非法业务响应：逐来源 outcome 和 `SourceFailure.source_id` 正确，整体航班结论为暂不可确认。
- 全部相关航班来源成功空结果：允许使用 `FLIGHT_PROVIDER_EMPTY` 和“未找到”，不得报告系统失败。
- 任一来源返回真实 offer：生成航班计划；其他来源失败保留说明但不污染真实 offer。
- 默认铁路+航班请求：铁路有计划、航班失败时响应为 `PARTIAL`。
- 显式排除航班：铁路有计划时可为 `COMPLETE`，不产生航班缺失警告。
- 仅允许航班且核心来源失败：不得返回铁路计划或虚构航班。
- 限流、超时、挑战、非法响应分别使用稳定错误码和正确 `retryable`。

## 2. 前端测试

- 铁路有计划、航班失败：同时看到“铁路可用”和“航班暂不可用”。
- 点击不可用航班只打开说明/重试，不进入详情、重算或预订。
- 有真实航班计划但三个推荐槽都指向铁路：仍能从航班入口访问并选择航班候选。
- 显式排除航班：不展示为失败；如显示入口，文案为“未纳入本次规划”。
- 重试航班来源时保留当前铁路内容、显示局部 loading，并防止重复提交。
- 旧 V1.17 响应只有聚合失败字符串：显示“暂不可确认”，不显示“没有航班”。
- 无任何路径生成占位航班号、价格、时刻或 plan_id。
- VoiceOver/TalkBack 能读出交通方式、可用/不可用和当前选择状态，触控区域满足现有 design system。

## 3. 合同与回归

- 前端 `TravelPlanResponse` 包含 `missing_plan_explanations`，与导出 schema 一致。
- 外部 schema version 保持 `1.17`，现有 plan/async/job/retry 响应可解析。
- `COMPLETE/PARTIAL/NO_MATCH/FAILED` 现有页面和异步轮询终态不退化。
- 铁路选择、席别同步、舱位重算、来源页和官方跳转回归通过。
- 东航 browser source 仍为禁用，测试不得通过修改门禁制造航班结果。

## 4. 建议执行

```powershell
.\.venv\Scripts\python -m pytest backend/app/tests/test_flight_providers.py backend/app/tests/test_planning_rules.py backend/app/tests/test_api.py -q
npm --prefix frontend test
npm --prefix frontend run typecheck
git diff --check
```

## 5. 通过标准

- 自动测试全部通过。
- 使用最后一次问题路线的脱敏 fixture 完成一次人工验收：航班缺口可见、状态准确、无虚构事实、重试受控。
- 真实环境 smoke 仅使用当前已批准来源；遇到 429 或挑战立即按 fail-closed 规则结束，不绕过风控。
