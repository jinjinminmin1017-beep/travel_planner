# 产品级 App Task Breakdown

日期：2026-06-05  
依据：`DATA_SCHEMA.md` V1.15 + `SYSTEM_ARCHITECTURE.docx` V1.1 + 真实 API 接入文档  
最终目标：交付可持续迭代、可灰度上线、具备真实数据边界和完整用户闭环的产品级 AI 出行规划 App。

---

## 1. P0 任务：必须先完成

### P0-01 App 客户端工程收口

状态：已完成（2026-06-05）

任务：

- 明确第一阶段只交付 Expo / React Native App。
- 清理或隔离不属于 App 交付路线的旧配置、旧脚本和旧说明。
- 修正 README 的 App 启动、调试、类型检查和构建命令。
- 修复 `npm run typecheck` 的依赖与 TS 配置问题。
- 明确 API Base URL 在本地、模拟器、真机、测试环境、生产环境下的配置方式。

验收：

- `npm run typecheck` 通过。
- App 入口、`package.json`、README、测试工具链一致。
- 新开发者可按 README 启动后端和 App。
- iOS 模拟器、Android 模拟器、真机调试至少有一条可验证路径。

### P0-02 Schema 合同差异审计与修复

任务：

- 对比 `DATA_SCHEMA.md` V1.15、`backend/app/models/schemas.py`、`schemas/*.schema.json`、`frontend/src/types/index.ts`。
- 统一枚举和值命名，重点检查：
  - `PlanLifecycleStatus`
  - `PlanningStatus`
  - `SourceFailureClass`
  - `SourceFailureHandlingStrategy`
  - `TransportMode`
  - `PlanType`
  - `RecalculateRequest.change_type`
  - `SelectedOption.option_type`
  - `RecalculateResponse.recalculate_scope`
- 统一金额、时间、GeoPoint、DataSourceMetadata、ErrorResponse、HealthResponse、DataSourceRuntimeStatus 字段。
- 为每个差异补测试，避免手工修完后再次漂移。

验收：

- Schema 导出文件与主文档 V1.15 语义一致。
- App 客户端类型由统一源生成或至少有自动 diff 检查。
- `scripts/export_schemas.py` 可重复执行且无非预期 diff。

### P0-03 API 错误与降级语义收口

任务：

- 统一所有错误路径复用 `ErrorResponse`。
- Provider 缺失、未授权、超时、空结果时，按数据源失败分级返回业务可理解结果。
- Planner 不能因为单个非关键 Provider 失败直接整体 500。
- 核心事实缺失时阻断对应方案类型，并填充 `SourceFailure`、`MissingPlanExplanation`、`missing_components`。
- 所有 SourceFailure 必须带 `request_id`、`trace_id`、`correlation_id`、`source_used_id`、`fallback_reason`。

验收：

- 覆盖 COMPLETE、PARTIAL、RUNNING、FAILED 的 TravelPlanResponse 示例和测试。
- 覆盖地图、铁路、航班、LLM、Redirect 的失败路径测试。
- App 能展示降级原因和下一步动作。

### P0-04 真实 Provider 配置检查进入 CI

任务：

- 将 `scripts/check_real_api_config.py` 和可免密 live smoke 拆成 CI 可运行的安全档位。
- CI 默认只跑无密钥、只读、低频 smoke。
- 有密钥环境再跑 Amadeus / 授权铁路 Partner smoke。
- 生产环境启动时校验未授权数据源不能启用。

验收：

- CI 能区分 fixture 测试、公开只读 smoke、密钥 Provider smoke。
- `.env.example` 与实际配置项完全同步。
- 生产环境 DataSourceConfig 未授权时启动失败或强制禁用。

### P0-05 产品能力矩阵文档化

任务：

- 在 docs 中维护产品能力矩阵：待实现、进行中、阻塞于授权、验收通过。
- 标记哪些测试 fixture 仅用于自动化，不得进入运行时 fallback。
- 标记 Planner 的路线覆盖范围和真实路线能力边界。

验收：

- 产品、开发、测试能从一份文档判断当前可演示能力。
- 每次新增 Provider 或规划能力同步更新。

---

## 2. P1 任务：核心产品闭环

### P1-01 LLM Intent Parser 产品化

任务：

- 按 `LLM_PROMPT_DESIGN.md` 实现 Prompt 模板、版本常量和 LLM 调用日志。
- 将当前规则解析器保留为 fallback 或测试路径。
- 增加 TravelRequest Schema 校验和语义校验。
- 增加一次 Repair Prompt。
- 解析失败时返回用户可补充的问题，而不是泛化报错。

验收：

- 覆盖日期、时间、地点、预算、交通方式排除、偏好、乘客备注、多轮补充信息。
- LLM 不得生成车次、航班、价格、余票或方案。
- 缺信息时 App 能引导用户补充。

### P1-02 地点解析与交通节点候选

任务：

- 用 Geocoding Adapter 替换 Planner 内硬编码坐标。
- 建立 Location Resolver：地址标准化、POI、城市识别、消歧。
- 建立 Station Candidate Generator 和 Airport Candidate Generator。
- 候选排序考虑距离、接驳耗时、费用、枢纽等级、班次密度和数据来源。

验收：

- 非样例城市可生成候选站/机场或清晰说明不可用。
- 每个候选带 DataSourceMetadata。
- 地点歧义时返回可选项。

### P1-03 本地接驳引擎

任务：

- 将 `_transfer_options` 升级为 Local Transfer Engine。
- 支持打车、地铁、公交、步行的可用性判断。
- 真实地图 Provider 返回距离、耗时、费用估算、步行距离和导航跳转。
- 支持起终点接驳、机场/车站接驳、跨站/跨机场接驳。

验收：

- Provider 不可用时按规则降级，不静默编造路线。
- App 展示每段接驳的上车/换乘/下车说明。
- 接驳方式切换后 1 秒级返回重算结果。

### P1-04 Rail Planning Engine

任务：

- 把当前硬编码车次搜索升级为动态铁路规划引擎。
- 支持直达、中转、多段中转和票源增强候选。
- 中转站动态生成，不写死城市。
- 票源增强严格执行 S / A / NOT_RECOMMENDED / BLOCKED 规则。
- 未取得中国铁路票价/余票授权前，铁路票价/余票能力必须保持阻断或只读说明。

验收：

- 至少覆盖直达、中转、票源增强 S/A/买短补长风险测试。
- 站序、安全关键数据缺失时阻断推荐。
- 不调用逆向接口，不自动登录、不抢票、不下单。

### P1-05 Flight Planning Engine

任务：

- 使用 Amadeus Flight Offers / Price 形成真实航班报价链路。
- 支持直飞、中转、多机场组合。
- 接入航班状态、天气、机场复杂度作为风险辅助。
- 跨航司、跨航站楼、重新安检、托运行李等风险结构化。

验收：

- 有 Amadeus test 环境 smoke 和 fixture 测试。
- 报价与可售状态标注数据来源、更新时间和最终平台确认提示。
- 航班核心事实缺失时不生成对应航班方案。

### P1-06 Candidate Plan Generator

任务：

- 将主交通和本地接驳组合成完整门到门方案。
- 原始候选、评分候选、LLM 候选池分层控制。
- 支持用户 hard constraints 过滤和 soft preferences 排序。
- 支持异步生成：先返回可用方案，再补充更多候选。

验收：

- 候选池进入 LLM 前为 5-15 条。
- 不满足硬约束的方案不进入推荐候选池。
- 每个被过滤方案可给出 MissingPlanExplanation 或用户可见原因。

### P1-07 Cost / Comfort / Risk 引擎

任务：

- 把费用、舒适度、风险从 Planner 辅助函数拆成独立模块。
- 费用全部使用 Money / MoneyDelta。
- 舒适度评分保留结构化 breakdown 和 score_version。
- 风险输出结构化 RiskItem，支持 LOW / MEDIUM / HIGH / BLOCKED。
- 数据质量输出 missing_components、warnings、confidence。

验收：

- 覆盖费用汇总、座席/舱位切换、接驳切换、风险阻断、数据质量降级测试。
- LLM 只解释，不计算事实字段。

### P1-08 LLM Recommendation Engine

任务：

- 完成 Recommendation Prompt、Schema 校验、Semantic Validator、Repair Prompt。
- 明确当前产品策略：LLM 不可用时是否返回 `recommendation_result = null`，并统一文档中 fallback 语义。
- 记录 LLMValidationResult、prompt_version、model_name、invalid_reasons。
- 禁止 LLM 选择 BLOCKED、不可选、过期或候选池外方案。

验收：

- 覆盖 REC-001 至 REC-012。
- LLM 输出非法时不展示非法结果。
- App 能展示推荐不可用状态和候选方案列表。

### P1-09 Recalculate 交互闭环

任务：

- 对齐 RecalculateRequest / RecalculateResponse 与 Schema V1.15。
- 支持座席、舱位、接驳方式切换后的费用、舒适度、风险、推荐结果重算。
- 支持 `PLAN_ONLY`、`PLAN_AND_RECOMMENDATION`、`FULL_REEVALUATION` 或产品最终确定的等价枚举。
- 增加幂等键处理。

验收：

- 覆盖 RQ-001 至 RQ-006。
- 目标 segment 或 option 不存在时返回业务错误。
- App 更新局部方案，不丢失其他候选。

### P1-10 Redirect-only Booking Handoff

任务：

- 完成 12306、航司官网、OTA、地图、打车跳转能力。
- 跳转请求不得携带登录、下单、支付、抢票参数。
- 每个 redirect 带 generated_at、expires_at、transaction_boundary、data_source。
- URL 不可用时返回 fallback_instruction。

验收：

- 覆盖 BR-001 至 BR-005、BRQ-001 至 BRQ-003。
- App 明确展示“跳转后以第三方平台为准”。
- 不保存第三方账号、密码、cookie、token。

---

## 3. P2 任务：App 产品体验

### P2-01 App 信息架构

任务：

- 设计并实现首页/输入页、规划中页、结果页、方案详情页、数据来源页、错误页、空结果页。
- 保持薄客户端：App 不调用第三方交通数据源、不计算复杂路线、不调用 LLM。
- 移动端优先优化输入、卡片横滑、详情展开、重算和跳转。

验收：

- 用户能完成“输入需求 -> 查看推荐/候选 -> 调整方案 -> 跳转确认”的闭环。
- 错误、降级、空结果都有明确下一步。
- UI 不依赖硬编码样例数据。

### P2-02 规划中与异步任务体验

任务：

- 支持 PENDING / RUNNING / PARTIAL / COMPLETE / FAILED 状态。
- 实现轮询或移动端推送通道。
- App 展示阶段进度：解析、地点、接驳、铁路、航班、评分、推荐。
- PARTIAL 状态可先展示已可用结果。

验收：

- 30 秒内返回首屏可用状态。
- 长耗时 Provider 不阻塞整个页面。
- 用户可以重试失败来源或改写需求。

### P2-03 方案详情与可信解释

任务：

- 展示费用明细、时间线、风险、舒适度拆解、数据来源、更新时间。
- 明确哪些数据是实时、估算、缺失或降级。
- 展示票源增强等级、原因和限制。
- 展示航班中转、重新安检、行李、延误等风险。

验收：

- 用户能理解为什么推荐该方案。
- 不出现“保证有票”“一定成功”等交易承诺。
- 数据源缺失不被隐藏。

### P2-04 App 设计系统与可访问性

任务：

- 建立颜色、字体、间距、按钮、卡片、表单、状态标签、风险标签组件。
- 适配小屏、大屏、动态字体、安全区域、横竖屏策略。
- 增加无障碍 label、触控区域、颜色对比。

验收：

- 核心页面在主流移动屏幕不重叠、不截断。
- 关键操作可被屏幕阅读器理解。
- 风险状态不只依赖颜色表达。

### P2-05 App 原生能力

任务：

- 支持系统定位权限请求和定位失败降级。
- 支持打开地图、航司、12306、OTA、打车平台的外部 App 或系统外部跳转入口。
- 支持分享方案、复制行程摘要、保存最近一次规划。
- 支持 App 后台恢复后刷新过期方案状态。

验收：

- 权限拒绝时 App 可继续手动输入地点。
- 外部跳转失败时有 fallback_instruction。
- 最近规划不保存第三方账号、支付或实名敏感信息。

### P2-06 用户反馈和问题上报

任务：

- 在结果页提供“路线不准/价格不准/跳转失败/看不懂”反馈入口。
- 反馈关联 request_id、trace_id、plan_id、source_id。
- 后台或日志能聚合高频问题。

验收：

- 用户反馈不包含敏感账号或支付信息。
- 开发能按 request_id 复盘问题。

---

## 4. P3 任务：基础设施与生产化

### P3-01 持久化与缓存

任务：

- 引入 PostgreSQL 保存用户请求、TravelRequest、TravelPlan 快照、Provider 调用日志、LLM 调用摘要、反馈。
- 引入 Redis 缓存地点解析、站点/机场候选、路线估算、Provider token、异步任务状态。
- 定义 TTL、失效策略和数据版本。

验收：

- 服务重启后可查询短期方案详情。
- 缓存命中不破坏 DataSourceMetadata。
- 敏感字段不落库或已脱敏。

### P3-02 异步任务与队列

任务：

- 为长耗时规划引入任务队列。
- 支持 job_id、job_status、polling_url、取消和超时。
- Provider 调用并发控制、超时、重试、fallback 策略配置化。

验收：

- 单个 Provider 慢不拖垮全部规划。
- 重复请求受 idempotency_key 控制。
- 任务状态符合 AsyncJob Schema。

### P3-03 可观测性

任务：

- 结构化日志统一输出 request_id、trace_id、correlation_id、source_id、failure_class、message。
- 增加 metrics：请求量、成功率、PARTIAL 率、Provider 延迟、Provider 失败率、LLM 修复率。
- 增加告警：核心 Provider DOWN、错误率异常、推荐不可用率异常。

验收：

- 一次用户请求可串联 API、Provider、LLM、App 反馈。
- 不记录第三方账号、token、支付或实名敏感信息。

### P3-04 鉴权、限流与安全

任务：

- 增加基础用户会话或匿名设备标识。
- API 限流、Provider QPS 限制、请求体大小限制。
- 密钥管理迁移到安全环境变量或密钥服务。
- 日志脱敏、异常信息脱敏、移动端证书/域名配置。

验收：

- 公网部署不会暴露 debug 异常。
- 未授权用户不能滥用 Provider。
- 生产配置不允许未审核数据源。

### P3-05 App 发布流水线

任务：

- 建立后端 lint/test/schema/export/build。
- 建立 App typecheck/test/build。
- 建立 staging 和 production 配置。
- 增加 release checklist 与 rollback checklist。
- 增加 iOS / Android 构建、签名、内测分发和正式发布步骤。

验收：

- 每次发布有可追踪版本。
- 失败可回滚。
- CI 能阻止 Schema 漂移和 App 类型失败进入主分支。
- App 构建产物可重复生成。

---

## 5. P4 任务：运营与增长能力

### P4-01 数据源运营后台

任务：

- 展示数据源健康、授权状态、最近失败、平均延迟、降级原因。
- 支持只读查看 DataSourceRuntimeStatus。
- 生产配置变更必须走审核，不在后台直接暴露密钥。

验收：

- 运营能判断当前哪些能力可用。
- 开发能定位 Provider 失败趋势。

### P4-02 搜索与规划质量评估

任务：

- 建立 golden route 集合。
- 记录方案覆盖率、推荐可用率、PARTIAL 率、用户选择率、跳转成功率。
- 为价格、耗时、风险和舒适度建立离线评估。

验收：

- 每次算法/Provider 改动可比较质量变化。
- 有可量化指标判断是否接近产品级。

### P4-03 多城市、多语言和个性化

任务：

- 扩展城市和交通模式覆盖。
- 支持英文或中英混合输入。
- 引入用户偏好记忆，但不得保存敏感第三方账号信息。

验收：

- 新城市接入无需改 Planner 硬编码。
- 个性化不会越过 hard constraints 和安全边界。

### P4-04 App 增长与留存

任务：

- 支持最近规划、收藏方案、行程提醒、价格/状态变化提醒。
- 支持用户明确授权后的目的地偏好和常用出发地。
- 建立 App 事件埋点：输入、规划成功、PARTIAL、推荐点击、跳转、反馈。

验收：

- 所有提醒和偏好均可关闭。
- 埋点不包含第三方账号、支付、实名敏感信息。
- 增长指标能和 request_id 脱敏关联。

---

## 6. 推荐执行顺序

1. P0-01 App 客户端工程收口。
2. P0-02 Schema 合同差异审计与修复。
3. P0-03 API 错误与降级语义收口。
4. P0-04 Provider 配置检查进入 CI。
5. P1-01 LLM Intent Parser 产品化。
6. P1-02 地点解析与交通节点候选。
7. P1-03 本地接驳引擎。
8. P1-04 / P1-05 铁路和航班规划引擎并行推进。
9. P1-06 至 P1-10 完成门到门方案、推荐、重算、跳转闭环。
10. P2 完成 App 产品体验。
11. P3 完成生产基础设施和 App 发布流水线。
12. P4 做运营和质量增长。

---

## 7. 产品级 Definition of Done

- 功能：核心用户路径完整，非样例城市可给出真实结果或明确降级原因。
- 数据：事实字段来自授权 Provider 或确定性计算，LLM 不编造事实。
- 合同：Schema V1.15、后端模型、App 类型、API 响应一致。
- 体验：推荐、候选、详情、重算、跳转、错误和空状态都可用。
- 性能：自然语言解析目标 3 秒内，节点解析目标 5 秒内，30 秒内有首屏状态，重算目标 1 秒内。
- 安全：不自动登录、不下单、不支付、不抢票、不保存第三方凭证。
- 可观测：每次请求可通过 request_id / trace_id / correlation_id 追踪。
- 质量：后端测试、App typecheck、Schema 校验、关键 E2E 全部进入 CI。
- 发布：有 staging、production、release checklist、rollback checklist、iOS / Android 发布流程。
