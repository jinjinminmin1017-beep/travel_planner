## ARC-TEST-20260712-01 约束无匹配与最近备选测试

来源：架构任务，2026-07-12。

完成状态：待测试。

### 测试目标

验证 `NO_MATCH` 能正确表达“查询成功但无方案满足硬约束”，最近备选来自可靠事实，安全门禁和 coverage 结论边界不会被绕过。

### 单元测试

- 时间计算器：最晚到达、最早出发、出发/到达时间窗，覆盖早于、命中边界、晚于和跨日期。
- 预算计算器：同币种 amount_minor 差值、等于预算、超预算；不同币种或 scale 不可直接比较。
- 交通方式计算器：allowed/excluded 集合、混合交通和空集合。
- 席位/舱位计算器：请求值可用、不可用和替代值。
- 安全门禁：`RiskLevel.BLOCKED`、核心事实缺失、低于绝对换乘安全线的候选不得进入 alternatives。
- Pareto：完全劣势方案被删除；时间更好但价格更差的方案与价格更好但时间更差的方案同时保留。
- 赛道选择：每类最多一个、总数不超过 3、按 plan_id 去重、结果顺序稳定。

### 后端集成测试

- 有满足硬约束方案：保持 `COMPLETE/PARTIAL`，`constraint_analysis` 为 null。
- 无匹配但有安全备选：HTTP 200、`NO_MATCH`、`plans=[]`、`recommendation_result=null`、`constraint_analysis` 非空。
- 无安全备选：`NO_MATCH + NO_SAFE_ALTERNATIVE`，alternatives 为空。
- 系统异常或核心事实完全不可用：仍为 `FAILED`，不得错误返回 NO_MATCH。
- 异步任务：最终 `planning_status=NO_MATCH`、`job_status=COMPLETE`、`progress=100`，轮询可结束。
- retry 接口遵守同一状态和结构。
- 持久化后读取仍能完整恢复 constraint_analysis 和备选 TravelPlan。
- Schema 导出与 Pydantic/前端类型一致，V1.16 strict validation 生效。

### Coverage 与文案测试

- 铁路 VERIFIED、航班 UNAVAILABLE：只能说“已验证铁路方案中最早”，不得说“所有交通方式中最早”。
- 铁路/航班均 VERIFIED 或 EMPTY：允许形成全覆盖结论。
- Provider TIMEOUT、FAILED、UNAVAILABLE 分别使用对应说明，不得统一写成“没有方案”。
- 摘要使用确定性模板，不能出现候选事实之外的车次、时间、价格或余票。

### 前端测试

- `NO_MATCH` 使用独立页面，不进入网络错误页或普通空态。
- 显示 summary、coverage、偏差方向和具体数值。
- 最多显示 3 个备选；备选明确标记不满足原始约束。
- 未确认前不能进入购票跳转。
- 确认放宽后发送新的 TravelRequest，且只修改用户确认的约束。
- `NO_SAFE_ALTERNATIVE` 显示修改需求入口，不显示空白方案卡。
- 新枚举不会导致轮询无限进行或被记录成 PLANNING_SUCCESS。
- `NO_MATCH` 只上报 `PLANNING_NO_MATCH`，metadata 不包含完整输入、详细地点或敏感乘客信息。

### 关键场景

1. 温州永嘉桥头梨村到武汉新天地，要求 2026-07-13 18:00 前到达；铁路均晚到、航班不可用。
2. 预算 500 元，最低可靠方案 620 元。
3. 一个方案晚到 10 分钟且预算内，另一个按时但超预算 20 元；两者均保留。
4. 一个方案更便宜但换乘低于绝对安全线；必须被门禁删除。
5. 用户明确排除飞机，只有飞行方案可按时到达；只能作为需确认的行为变化备选，不能自动推荐。

### 回归命令

- `python -m pytest backend/app/tests`
- `npm run typecheck`（`frontend/`）
- `npm run test:helpers`（`frontend/`）
- `python scripts/export_schemas.py` 后检查 `schemas/` diff

### 通过标准

- 所有新增和既有测试通过。
- 正常 COMPLETE/PARTIAL、重算、跳转和推荐链路无回归。
- 不存在跨单位通用分数。
- LLM 不参与硬约束、偏差、安全门禁或备选事实生成。
