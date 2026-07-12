# ARC-20260712-02 修正地图降级语义并实现结果集席别传播

来源：架构任务，2026-07-12。

完成状态：已完成。完成时间：2026-07-12 09:36:27 +08:00。代码提交：`3f17f50fd1d04bf9c92c9faaa47e5633b9bec96e`。

## 背景

用户反馈：结果页显示“地图 Provider 不可用”；完整路线中修改动车席别后，返回门到门路线时其他推荐方案仍是旧席别。

已确认：

- 2026-07-12 真实地图 smoke 通过，高德路线、地图跳转可用；上海样例的打车、地铁、公交、步行均能返回。
- 当前地图问题是失败聚合和展示范围过大，不应按整体 Provider 宕机处理。
- 当前 `/api/travel/recalculate` 只更新一个 plan，前端也只替换一个 plan，无法实现结果集级偏好传播。

详细设计见：

- `docs/ARCHITECTURE.md` “地图路线降级与结果集席别偏好架构”
- `docs/API_CONTRACT.md` “结果集席别重算目标契约（V1.17）”

## 开发任务 A：地图状态语义

1. 为地图 Provider 声明支持的 `TransportMode`，调度前过滤能力不匹配 Provider。
2. 禁止 OSRM driving 结果用于 SUBWAY、BUS、WALK；保留其真实支持的驾车/打车类能力。
3. 区分以下结果：首选成功、备用成功、规则估算、不可用、坐标缺失、超时、限流、空结果、未启用。
4. `local_transfer_engine.py` 不再因任一未选接驳 option 失败就写全局 `missing_components=map_route`。
5. 仅当前选中接驳方式依赖规则估算/不可用时，才影响该计划与整体 `PARTIAL` 状态。
6. 备用 Provider 成功时主文案强调已有可用路线；坐标缺失不得写成 Provider 不可用。
7. 详细 `SourceFailure`、fallback source 和 error code 继续保留，便于数据来源页与日志诊断。
8. 扩展 `live_smoke_real_apis.py`：按 Provider 声明能力至少覆盖驾车；高德启用时覆盖步行和公共交通，并明确具体失败方式。

## 开发任务 B：结果集席别传播

1. Schema version 升到 `1.17`；新增 `application_scope=TARGET_PLAN|RESULT_SET`。
2. `RecalculateResponse` 增加 `updated_response` 和结构化 `preference_application`；保留单 `plan` 兼容字段。
3. 前端完整路线席别调整发送 `RESULT_SET + FULL_REEVALUATION`；接驳调整仍发送 `TARGET_PLAN`。
4. 后端从目标 segment 的 option_id 解析 canonical seat_type，忽略前端 label 的事实权威性。
5. 更新结果集 `TravelRequest.preferred_rail_seat` 和 `preference_source=USER_EXPLICIT`。
6. 遍历同一响应中的全部计划和全部铁路段，按 seat_type 匹配各段自己的合法 option_id。
7. 每个计划独立重算费用、舒适度、质量与摘要；不得复制目标计划票价。
8. 不支持所选席别的计划退出推荐候选池，写入 `unsupported_plan_ids`，但可作为带明确原因的其他候选展示。
9. 在过滤后的完整候选集上重新运行 Recommendation；AVAILABLE 推荐不得包含旧席别。
10. 抽出结果集偏好应用器，避免继续扩大 `planner.py`；建议放在 `backend/app/services/` 下独立模块。
11. 先构造并校验完整新快照，再原子更新 `PLANS`、`RESPONSES`、`PLAN_RESPONSES` 与持久化；禁止部分提交。
12. 前端收到结果后整体替换 `response`；保留当前 plan_id，若不可推荐则切换到首个可用推荐方案。
13. 最近规划/收藏继续保存更新后的选中方案，不得在重算过程中保存半更新快照。

## 主要文件范围

- `backend/app/models/schemas.py`
- `backend/app/data_sources/map_providers.py`
- `backend/app/services/local_transfer_engine.py`
- `backend/app/services/planner.py`
- `backend/app/services/candidate_generator.py`
- `backend/app/services/store.py`
- `backend/app/services/persistence.py`
- `backend/app/main.py`
- `frontend/src/types/index.ts`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/results/RouteDetailScreen.tsx`
- `frontend/src/components/results/ResultsOverview.tsx`
- `scripts/live_smoke_real_apis.py`
- `schemas/*.schema.json`

## 非目标

- 不让 LLM 决定或生成席别、option_id、票价和可用性。
- 不把一次席别选择持久化为跨行程账号偏好；第一阶段仅作用于当前结果集。
- 不把所有接驳方式都自动传播到所有计划。
- 不新增未经批准的商业地图 Provider。

## 验收标准

- Provider 健康时，未选备选路线失败不会让结果页显示“地图 Provider 不可用”。
- 备用地图成功时结果可用，文案明确是备用来源；规则估算只限定到具体接驳段。
- OSRM 不再以 driving 路线伪装地铁、公交或步行路线。
- 在任一推荐方案详情选择一等座后，返回门到门结果，所有 AVAILABLE 铁路推荐均为一等座且价格分别正确。
- 不提供一等座的方案不会继续占据推荐卡，并有明确说明。
- 重算响应、plan 查询、再次重算和跳转读取到同一结果集版本。
- 后端测试、前端 typecheck/helper tests、schema export/diff 全部通过。

## 风险与回滚

- 使用功能开关控制 RESULT_SET 席别传播；关闭时保持旧 TARGET_PLAN 行为并同步收敛前端承诺。
- 新字段提供默认值/可空兼容，保证灰度期间旧客户端可解析。
- 地图展示聚合可独立回滚，但 Provider capability 过滤不可通过伪造 mode 结果回滚。
