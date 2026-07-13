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

---

# ARC-20260712-03 修复规划任务混用无时区与带时区时间导致失败

来源：用户反馈与架构诊断，2026-07-12。

完成状态：已完成。完成时间：2026-07-12 19:45:40 +08:00。代码提交：`23ed0e9290a22ebe0010946d4b0de677a7b9db67`。

## 问题与证据

最近两次异步规划任务均稳定失败：

- `job_13fd1b3fb2e4`：12306 成功返回 9 个车次并生成候选后失败。
- `job_5ec92410ec34`：重试命中铁路缓存并生成 4 个候选后再次失败。
- 两次最终状态均为 `planning_status=FAILED`、`job_status=FAILED`，异常均为 `can't compare offset-naive and offset-aware datetimes`。

失败请求中的 `latest_arrival_time.datetime` 为无时区值 `2026-07-15T17:00:00`，但同时声明 `timezone=Asia/Shanghai`；铁路候选到达时间为带 `+08:00` 的 aware datetime。候选进入时间约束计算后直接比较两者，触发 Python `TypeError`。

根因链路：

1. `TravelRequest.model_validate()` 接受无 `tzinfo` 的 `TimePoint.datetime`。
2. `validate_travel_request_semantics()` 只检查 `timezone` 字符串非空，没有检查或规范化 `datetime.tzinfo`。
3. `generate_candidate_plan_pool()` 调用约束评估。
4. `constraints/time_calculator.py` 直接执行 naive/aware datetime 比较和相减。
5. `_complete_plan_job()` 捕获异常并把任务转为 FAILED，但未记录异常堆栈，且把内部异常原文暴露给用户。

## 修复目标

- 所有进入业务层的 `TimePoint` 都必须具有可比较的、明确的时区语义。
- 兼容已经发送“无偏移 datetime + timezone 字段”的客户端和 LLM 输出，不要求用户重试或修改输入格式。
- 时间约束计算不得因时区表示差异抛出系统异常。
- 后台任务异常必须可通过 request/job/trace 关联诊断，同时不向用户暴露 Python 内部异常。
- 不修改现有 API 字段、枚举或 schema version，不引入数据库迁移。

## 后端开发任务

1. 在 `TimePoint` 模型边界增加统一时区规范化：
   - 使用标准库 `zoneinfo.ZoneInfo` 解析 `timezone`。
   - `datetime.tzinfo is None` 时，按 `timezone` 附加时区。
   - datetime 已带时区时，转换到 `timezone` 声明的目标时区。
   - 非法或空时区返回明确的 Pydantic 校验错误，不进入规划链路。
   - `source_timezone` 作为来源元数据保留；为空时可回填为 `timezone`，不得用它覆盖目标时区。
2. 统一时间比较入口：
   - `constraints/time_calculator.py` 不再散落直接比较未经规范化的 datetime。
   - 比较与分钟差计算统一使用 aware datetime；建议转换到 UTC 后比较。
   - 保持现有偏差方向、分钟取整和用户文案语义不变。
3. 扩充 `validate_travel_request_semantics()`：
   - 覆盖 `time_window_start`、`time_window_end`、`earliest_departure_time`、`latest_arrival_time`、`preferred_departure_time`。
   - 覆盖 `hard_constraints` 下全部 TimePoint。
   - 校验时区已被正确规范化，而不只检查字符串存在。
4. 改进异步后台异常处理：
   - `_complete_plan_job()` 捕获异常时调用 `logger.exception`。
   - 日志必须带 `job_id`、`request_id`、`trace_id`、`correlation_id`，但不得记录完整用户输入、凭证或其他敏感信息。
   - `user_visible_warnings` 改为稳定的通用提示，不拼接 `str(exc)`。
   - 保留任务可轮询的 FAILED 业务状态，避免后台异常变成无响应任务。
5. 检查持久化兼容：旧 SQLite/缓存 JSON 在重新通过 Pydantic 加载时应完成同样规范化；不得要求数据库迁移或批量重写历史记录。

## 主要文件范围

- `backend/app/models/schemas.py`
- `backend/app/services/intent_parser.py`
- `backend/app/services/constraints/time_calculator.py`
- `backend/app/main.py`
- `backend/app/tests/test_models.py`
- `backend/app/tests/test_constraints.py`
- `backend/app/tests/test_api.py`
- `backend/app/tests/test_logging.py`（如复用现有日志测试更合适）

## 测试要求

1. `TimePoint` 接收 `2026-07-15T17:00:00 + Asia/Shanghai` 后，结果必须带 `+08:00`。
2. 已带 `+08:00` 的 TimePoint 保持同一时刻和目标时区语义。
3. 带其他合法 offset 的时间转换到声明时区后仍表示同一绝对时刻。
4. 非法 IANA timezone 必须在模型边界返回校验错误。
5. LLM 输出无 offset 的 `latest_arrival_time` 时，Intent Parser 应通过规范化并保持语义校验成功。
6. aware 候选与上述请求进入 `evaluate_time_constraints()` 时不得抛异常，应正常返回满足项或结构化 violation。
7. 使用本次失败形态的异步 API 回归用例，轮询终态不得因时间比较进入 FAILED；根据候选应返回 COMPLETE、PARTIAL 或 NO_MATCH。
8. 后台人为异常测试需确认日志含任务关联 ID，前端警告不包含 Python 异常原文。
9. 保留现有规则解析器、铁路 Provider、约束无匹配和 schema export 测试，避免时区修复改变正常结果。

## 验收标准

- 本次两个失败任务对应的输入形态可以完成规划，不再出现 naive/aware datetime 异常。
- 12306 成功返回候选后，约束计算能稳定完成并输出正常终态。
- 时间偏差按绝对时刻计算，跨 offset 输入不会出现提前/晚到方向颠倒。
- API 响应结构和 schema version 保持 V1.17，不需要前端同步改字段。
- 用户界面不再显示 Python 内部异常文本；后端日志可用 job/request/trace 定位完整堆栈。
- 执行并通过：
  - `python -m pytest backend/app/tests/test_models.py`
  - `python -m pytest backend/app/tests/test_constraints.py`
  - `python -m pytest backend/app/tests/test_api.py`
  - `python -m pytest backend/app/tests/test_logging.py`
  - `python -m pytest backend/app/tests`

## 风险与回滚

- 风险：直接给 naive datetime 附加时区代表“按声明时区解释本地墙上时间”，这是兼容当前合同的预期行为；不得把 naive 值误当 UTC。
- 风险：历史数据中的 `timezone` 若为非法值，加载时会从静默接受变成明确失败；应返回可诊断错误，不可猜测时区。
- 风险：时区规范化应在模型边界完成，避免只修约束计算而让其他模块继续接收 naive datetime。
- 回滚：如模型级规范化造成未预期兼容问题，可暂时在 Intent/API 输入边界使用同一规范化函数；不得回滚为直接比较 naive/aware datetime。

---

# ARC-20260712-04 接入高德地点搜索并移除接驳规则估算

来源：用户确认的架构决策，2026-07-12。

完成状态：已完成（2026-07-13，代码提交 `7603cf3`）。

## 目标

- 任意高德可搜索地点先解析真实坐标，再调用高德路线规划。
- 删除接驳距离、耗时和费用的规则估算路径。
- 地点或路线不可验证时让对应门到门计划退出正常推荐，不生成看似完整的假数据。

## 开发任务

1. 在 `geocoding_providers.py` 新增高德地点解析 Provider，支持地址地理编码和 POI 关键字搜索，复用现有高德 Web Service key，但使用独立 `source_id`、能力和可观测性记录。
2. 在 `data_sources.dev/test/prod.json`、`config_loader.py`、`.env.example` 增加高德地理编码配置；不得提交真实 key。
3. 将 `resolve_location_point()` 升级为 Provider-aware 解析：本地缓存/节点目录 → 高德地理编码 → 高德 POI 搜索；接收城市上下文并返回来源、状态和候选，而不是只返回裸 `GeoPoint | None`。
4. 对多候选按城市、规范化名称和完整地址消歧；仍不唯一时返回 `MAP_LOCATION_AMBIGUOUS`，不默认取第一条。
5. 在一次规划任务内批量解析并缓存唯一地点；同一地点不得因多个计划和多个接驳方式重复请求高德。
6. 删除 `local_transfer_engine.py` 的固定分钟、固定距离、固定费用 fallback；不得再构造 `RULE_ESTIMATED` option/segment。
7. 只保留地图 Provider 验证成功的接驳 option。选中方式失败但其他方式成功时，选择可用方式并明确来源；全部失败时返回接驳不可用结果。
8. `planner.py` 在必需首程/末程接驳无任何验证方式时移除该门到门计划的推荐资格，并写结构化 `SourceFailure`、`missing_plan_explanations`。
9. 聚合同一地点对的重复失败，前端主 warning 只显示一次；详细 Provider 尝试保留在数据来源页和日志。
10. V1.17 暂时保留 `RULE_ESTIMATED` 枚举供旧响应解析，但新规划、重算和重试结果均不得生成该状态。
11. 前端不得为 UNAVAILABLE 接驳自行填充默认时间、距离或费用；只展示已验证方式或明确的“无法形成完整门到门路线”。
12. 扩展真实 API smoke，至少验证“温州永嘉桥头梨村 → 温州南站”和“武汉站/武汉东站/汉口站 → 武汉新天地”的地点解析及驾车路线。

## 主要文件

- `backend/app/data_sources/geocoding_providers.py`
- `backend/app/data_sources/config_loader.py`
- `backend/app/data_sources/data_sources.*.json`
- `.env.example`
- `backend/app/services/location_resolver.py`
- `backend/app/services/local_transfer_engine.py`
- `backend/app/services/planner.py`
- `backend/app/services/candidate_generator.py`
- `backend/app/services/cache_store.py`
- `backend/app/models/schemas.py`
- `frontend/src/types/index.ts`
- `frontend/src/components/results/RouteDetailScreen.tsx`
- `frontend/src/components/results/ResultsOverview.tsx`
- `scripts/live_smoke_real_apis.py`

## 验收标准

- 本次真实输入不再出现“尚未搜索高德就坐标不完整”。
- 高德成功搜索地点后，接驳段使用高德路线返回的真实距离和耗时。
- 新响应中 `RULE_ESTIMATED` 出现次数为 0。
- 高德返回歧义、空结果、超时或限流时，不生成估算数字；对应门到门计划退出正常推荐并给出准确原因。
- 同一地点在单次规划中最多执行一次有效搜索链路，缓存命中可复用。
- 后端全量测试、前端 typecheck/helper tests、schema export/diff 和真实地图 smoke 全部通过。

## 风险与回滚

- 真实地点搜索增加外部调用时延，必须使用任务级去重、TTL 缓存和 Provider QPS 控制。
- 同名 POI 可能产生歧义，必须要求城市一致或用户补充地址。
- 回滚只能关闭新高德搜索 Provider并将接驳标为不可用；禁止恢复规则估算。
