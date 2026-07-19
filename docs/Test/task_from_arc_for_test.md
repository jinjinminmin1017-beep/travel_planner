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

---

## ARC-TEST-20260712-02 地图降级语义与结果集席别传播测试

来源：架构任务，2026-07-12。

完成状态：待测试。

### 地图 Provider 单元测试

- Provider capability：OSRM driving 只接收驾车/打车类 mode；SUBWAY、BUS、WALK 不得被路由给不支持的 Provider。
- 首选成功：无 fallback failure、无全局 map_route missing。
- 首选失败、备用成功：返回可用 estimate，记录 fallback 来源；主文案不得写成所有地图 Provider 不可用。
- 坐标缺失：error code 为 `MAP_COORDINATES_MISSING`，不得使用 `PROVIDER_DOWN`/整体不可用语义。
- 超时、限流、空结果、未启用分别保留独立状态。

### 地图规划集成测试

- 未选的公交备选失败、当前选中打车成功：计划不因公交失败变为 PARTIAL，结果页主 warning 不显示地图不可用。
- 当前选中方式只能规则估算：计划为 PARTIAL，文案限定到具体接驳段，不宣称 Provider 整体宕机。
- 多个接驳段仅一个降级：SourceFailure 能定位受影响段/方式，其他段保持 verified 来源。
- 数据来源页仍能查看详细失败和 fallback，不因主警告收敛而丢失诊断信息。
- live smoke 至少覆盖驾车；高德启用环境覆盖步行与公共交通。

### 席别传播单元测试

- 后端由目标 option_id 解析 seat_type；伪造 option_value 不得改变 canonical_value。
- 不同车次使用不同 option_id 但 seat_type 相同：分别选中各自 option_id。
- 多铁路段方案：所有铁路段都应用所选席别，不能只改第一段。
- 每个计划按自己的席别价格重算，费用 delta 不串用。
- 不支持所选席别的计划进入 unsupported_plan_ids 且退出推荐候选。
- 未知席别 label 不做模糊猜测。

### 重算 API 集成测试

- `TARGET_PLAN` 保持旧的单计划行为。
- `SEAT_TYPE + RESULT_SET + FULL_REEVALUATION` 返回完整 updated_response 和 preference_application。
- updated_response.travel_request 写入 preferred_rail_seat，preference_source 为 USER_EXPLICIT。
- 所有 AVAILABLE 推荐计划的每个铁路段均匹配 canonical seat_type。
- 可推荐计划不足三个时，缺少的 slot 为 NOT_AVAILABLE，不得用旧席别方案补位。
- 没有任何计划支持时响应可解释且无 AVAILABLE 推荐，不静默回退。
- `LOCAL_TRANSFER_MODE + RESULT_SET` 返回 422 VALIDATION_ERROR。
- 同一 idempotency key 重试返回相同完整结果版本。
- 构造/校验中途失败时，所有 plan 与 response 索引均保持旧版本，不得部分更新。
- 重算后 `GET /api/travel/plans/{plan_id}`、再次重算、跳转均消费更新快照。

### 前端测试

- 完整路线席别操作发送 RESULT_SET，接驳方式发送 TARGET_PLAN。
- 更新过程中保留旧门到门结果并显示局部 loading；失败不清空旧结果。
- 成功后整体替换 response，而非只 map 替换一个 plan。
- 返回门到门路线后，推荐卡、时间线、详情中的席别和价格一致。
- 当前 plan 仍可用时保持选中；退出推荐资格时切到首个可用推荐方案。
- unsupported 方案显示明确说明，不以旧席别继续作为推荐。

### 回归命令

- `python -m pytest backend/app/tests`
- `npm run typecheck`（`frontend/`）
- `npm run test:helpers`（`frontend/`）
- `python scripts/export_schemas.py` 后检查 `schemas/` diff
- `python scripts/check_real_api_config.py --tier public`
- `python scripts/live_smoke_real_apis.py --tier public`

### 通过标准

- 地图健康、精确查询失败和规则估算三种语义不再混淆。
- 结果集席别传播、推荐重排、持久化和前端展示保持一致。
- 现有正常规划、NO_MATCH、单计划接驳重算、购票跳转无回归。

---

## ARC-TEST-20260712-03 高德地点搜索与无规则估算接驳测试

来源：架构任务，2026-07-12。

完成状态：待测试。

### Provider 与地点解析

- 本地目录命中时不调用高德；未命中时依次测试高德地理编码和 POI 搜索。
- 高德地址结果唯一、POI 结果唯一、按城市消歧成功三种情况均返回完整坐标与来源。
- 多个同城同名结果无法唯一确定时返回 `MAP_LOCATION_AMBIGUOUS`，不得取第一条。
- 空结果、超时、限流、非法响应分别保留独立失败状态。
- 同一规划内重复地点只调用一次搜索链路；跨任务 TTL 缓存按配置生效。

### 接驳与规划

- 删除/禁止所有固定分钟、固定距离和固定费用 fallback；新增断言确保新响应不存在 `RULE_ESTIMATED`。
- 一种方式失败、另一种方式成功时，只返回验证成功的 option，计划可继续。
- 必需首程或末程全部方式失败时，门到门计划不进入正常 plans/AVAILABLE 推荐，并且不包含估算接驳数字。
- 相同地点对在多个计划中失败时，响应主警告去重，结构化日志仍可关联 Provider 尝试。
- 前端不为不可用接驳补默认数字，不把干线方案显示成完整门到门推荐。

### 真实 smoke

- 验证 `温州永嘉桥头梨村 → 温州南站`。
- 验证 `武汉站 → 武汉新天地`、`武汉东站 → 武汉新天地`、`汉口站 → 武汉新天地`。
- 每个案例记录地点搜索来源、坐标、路线 Provider、距离和耗时；日志不得记录 API key。

### 回归命令与通过标准

- `python -m pytest backend/app/tests`
- `npm run typecheck`（`frontend/`）
- `npm run test:helpers`（`frontend/`）
- `python scripts/export_schemas.py` 后检查 schema diff
- `python scripts/check_real_api_config.py --tier public`
- `python scripts/live_smoke_real_apis.py --tier public`
- 所有新增与既有测试通过，新任务响应中 `RULE_ESTIMATED` 为 0，Provider 失败不产生虚构接驳事实。
