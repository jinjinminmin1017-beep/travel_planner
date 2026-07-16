# 产品级 App Task Breakdown

日期：2026-06-05  
依据：`DATA_SCHEMA.md` V1.15 + `SYSTEM_ARCHITECTURE.docx` V1.1 + 真实 API 接入文档  
最终目标：交付可持续迭代、可灰度上线、具备真实数据边界和完整用户闭环的产品级 AI 出行规划 App。

---

## 1. P0 任务：必须先完成

### P0-01 App 客户端工程收口

状态：已完成（2026-06-05）

执行记录：2026-06-16 已完成代码废弃逻辑审阅，识别旧模板引擎残留、未接入队列配置、未使用前端导出和本地生成目录等待清理项；本次仅审阅和标记，不删除业务代码。

执行记录：2026-06-23 已新增 `scripts/device-debug.ps1`，一键启动真机调试后端与 Expo LAN 服务，自动设置 `EXPO_PUBLIC_API_BASE_URL`，并生成 `logs/expo-go-qr.png` 扫码图片；README 已同步脚本用法。
执行记录：2026-06-23 已修复真机调试脚本端口占用处理：当 8000/8081 已被旧后端或旧 Expo 占用时，脚本会自动选择后续空闲端口并用新端口生成 QR 与 API Base URL，避免手机继续连到旧服务。
执行记录：2026-07-05 已优化 `scripts/device-debug.ps1` 退出清理：Ctrl+C 结束真机调试时会递归停止后端/Expo 父子进程，并按本次实际使用端口清理仍在监听的残留进程，避免 8000/8081 或自动递增端口被本次调试会话继续占用。
执行记录：2026-07-05 已完成 APP 工程分层文档设计，新增 `docs/PROJECT_INDEX.md`、`docs/ARCHITECTURE.md`、`docs/API_CONTRACT.md`，记录当前前端、后端、配置、测试、脚本、类型合同与已发现 API，降低后续 Codex 任务上下文读取成本；本次未开发业务代码。

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

状态：已完成（2026-06-14；`.env.example` 已恢复为无密钥安全模板，真实 `.env` 可按用户自有高德、官方公开航司采集源等合规配置启用 Provider；配置检查脚本可区分模板安全档与本地显式审批运行档）

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

状态：已完成（2026-06-11）

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

状态：已完成（2026-06-11）

任务：

- 将 `scripts/check_real_api_config.py` 和可免密 live smoke 拆成 CI 可运行的安全档位。
- CI 默认只跑无密钥、只读、低频 smoke。
- 显式审批环境再跑官方公开航司采集源 / 授权铁路 Partner smoke。
- 生产环境启动时校验未授权数据源不能启用。

验收：

- CI 能区分 fixture 测试、公开只读 smoke、密钥 Provider smoke。
- `.env.example` 与实际配置项完全同步。
- 生产环境 DataSourceConfig 未授权时启动失败或强制禁用。

### P0-05 产品能力矩阵文档化

状态：已完成（2026-06-12）

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

状态：已完成（2026-06-12）

执行记录：2026-06-23 已修复规则解析器对中文点号日期的识别，支持 `2026年6.24号`、`2026/6/24`、`6.24号` 等输入，并补充真机反馈原句回归测试。

执行记录：2026-06-23 已修复真实 LLM 解析链路配置排查问题：`REAL_LLM_BASE_URL` 应填写 OpenAI-compatible 根路径而不是 `/chat/completions` 完整路径；同时补强 Intent Parser Prompt 的 TravelRequest 字段约束，并在 LLM 输出字段不合规且 Repair 失败时回退规则解析器，避免自然语言输入被直接阻断。

执行记录：2026-06-23 已将真实 LLM HTTP 超时从固定 15 秒调整为 `REAL_LLM_TIMEOUT_SECONDS` 可配置项，本地默认配置为 45 秒，以适配 Ark/Doubao 在较长 Intent Parser Prompt 下的响应耗时。
执行记录：2026-06-23 已修复日期前缀自然语言输入的规则 fallback，例如 `6.26上午，从上海东方明珠塔到云南洱海`；真实 LLM 输出缺失起终点且 Repair 失败时，规则解析器现在可以正确解析出发地、目的地和日期。
执行记录：2026-06-28 已验证本地 `.env` 中真实 LLM 配置可用：`REAL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`、`REAL_LLM_MODEL=glm-5.2` 可通过 OpenAI-compatible `/chat/completions` 返回 JSON 内容；项目 `real_llm` Provider 构建与调用链路同步验证通过。
执行记录：2026-07-07 架构侧已更新 Intent Parser Prompt 设计口径：`TravelRequest Schema V1.15` 仅作为后端校验契约和版本标识，运行时 Prompt 必须给出最小字段契约与关键枚举；Intent Parser 只做用户输入意图解析，不做路线规划、票价生成、推荐排序或数据源查询。代码侧需同步精简 `backend/app/llm/prompts/intent_parser_prompt_v1_0.txt` 与 `llm_providers.py` 中的 user prompt。

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

状态：已完成（2026-06-12）

执行记录：2026-06-23 根据真机日志 `6.26号上午，从上海静安寺到武汉天地` 补充武汉地点/交通节点覆盖，新增武汉天地、武汉站、汉口站、武昌站和武汉天河机场候选，避免目的地城市为空导致 `route_coverage` 失败。

任务：

- 用 Geocoding Adapter 替换 Planner 内硬编码坐标。
- 建立 Location Resolver：地址标准化、POI、城市识别、消歧。
- 建立 Station Candidate Generator 和 Airport Candidate Generator。
- 候选排序考虑距离、接驳耗时、费用、枢纽等级、班次密度和数据来源。

验收：

- 非样例城市可生成候选站/机场或清晰说明不可用。
- 每个候选带 DataSourceMetadata。
- 地点歧义时返回可选项。

执行记录：2026-06-23 已完成 `geocode addressdetails -> 城市归一化 -> 交通节点目录` 链路；站点/机场候选改由 `backend/app/data/transport_nodes.json` 生成，Location Resolver 不再为交通节点维护逐城市 Python 常量，目录缺失时不会编造站点。
执行记录：2026-06-23 已新增交通节点 Catalog Provider 与 `scripts/import_transport_nodes.py`，从 12306 官方站名目录导入铁路站点/城市/电报码，并从 OurAirports CSV 导入中国机场目录；当前生成目录包含 3380 个铁路站点和 417 个机场，铁路站点坐标缺失时会按枢纽等级排序并显式标注坐标边界。
执行记录：2026-06-24 已修正 OurAirports 中国机场城市归一化：导入时使用 12306 城市拼音别名把 `Sanya` 等英文 municipality 映射到中文城市名，三亚凤凰机场等机场候选可按中文目的地命中；同时保留内部中文 seed 节点优先级，避免英文机场名覆盖既有中文展示。
执行记录：2026-06-25 已统一 `transport_nodes.json` 节点 schema：内部 seed 与外部导入节点均补齐 `node_type`、外部代码、来源、授权、导入时间和坐标质量字段；导入合并逻辑会在写出前规范化 existing catalog，避免短字段 seed 与长字段导入节点混用。
执行记录：2026-06-27 已修复 POI/车站地点解析被城市别名误覆盖的问题：`上海东方明珠塔`、`成都太古里` 已补充精确坐标，`上海虹桥站`、`成都东站` 等交通节点会优先于 `上海`/`成都` 城市别名匹配；避免接驳路线用城市中心或春熙路等代表点估算。
执行记录：2026-06-27 已移除地点记录中的城市级别别名宽松 contains 匹配：`上海`、`成都` 等城市 alias 仅用于明确城市解析/歧义候选，不再把 `上海未知展馆`、`成都东站` 这类具体地点误命中到 `上海市区` 或 `成都春熙路`。
### P1-03 本地接驳引擎

状态：已完成（2026-06-12）
执行记录：2026-06-27 已修正本地接驳距离/时间/费用一致性：接驳 option 现在保留地图 Provider 返回的 `distance_meters`，选中接驳段直接继承真实路线距离，不再用默认分钟反推距离；东方明珠到上海虹桥站、成都东站到成都太古里已用高德 live 路线校验并回归到合理量级。

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

状态：已完成（2026-07-04；铁路事实源已收口为 `rail_12306_public_query`，运行时 Planner 按地点解析出的候选站点生成站点对查询，由 12306 公开匿名查询返回真实车次、时刻、席别和票价后再组装门到门方案；Provider 只返回有可用席别且有票价的铁路 offer，余票字段仅后端内部筛选使用，App 不展示余票状态或数量；旧第三方铁路 API、海外铁路连接和购票平台代理代码、配置、测试与文档均已移除；中转、多段、票源增强、航班和航铁混合在事实缺失时继续以能力缺口阻断，不用旧模板补造。）

执行记录：2026-06-24 已接入动态铁路中转 Planner：当直达铁路 Provider 未返回可验证车次时，Planner 会从交通节点目录按城市/地理绕行成本生成中转站候选，分别查询两段铁路 Provider offer，并仅在两段真实车次满足最小换乘时间时生成 `TRANSFER_RAIL`，不再使用旧中转模板补造方案。
执行记录：2026-07-01 已收敛铁路 Provider 限流后的本轮规划控制流：当直达铁路查询返回 `RAIL_PROVIDER_RATE_LIMITED` 后，Planner 会阻断后续铁路中转与航铁混合中的铁路查询，不再在同一次规划里继续调用铁路事实源；补充回归测试断言限流场景整轮只调用一次铁路搜索，且不新增运行时 fallback 或旧模板补造。
执行记录：2026-07-04 已将铁路 Provider 替换为 `Official12306RailProvider` / `rail_12306_public_query`：通过站点电报码查询 12306 公开匿名票务结果，解析车次、时刻、席别与票价；缺站点码、无票、缺价、限流或页面结构变化时写入 `SourceFailure` / `MissingPlanExplanation` 并阻断对应铁路方案；同步删除旧第三方铁路 API、海外铁路连接、购票平台代理 Provider、配置、live smoke、测试、schema 枚举和前端余票展示文案。

任务：

- 把当前硬编码车次搜索升级为动态铁路规划引擎。
- 支持直达、中转、多段中转和票源增强候选。
- 中转站动态生成，不写死城市。
- 票源增强严格执行 S / A / NOT_RECOMMENDED / BLOCKED 规则。
- 铁路事实源必须限定为 12306 公开匿名查询能力；缺站点码、无票、缺价、限流或页面结构变化时必须阻断对应铁路方案。

验收：

- 至少覆盖直达、中转、票源增强 S/A/买短补长风险测试。
- 站序、安全关键数据缺失时阻断推荐。
- 不调用逆向接口，不自动登录、不绕验证码、不抢票、不下单、不支付；App 不展示余票状态或数量。

### P1-05 Flight Planning Engine

状态：已完成（2026-07-04；规划引擎已改为消费自采官方公开航司 Provider，真实航班报价必须来自已审批源站的真实价格、真实舱位和可售信号）
执行记录：2026-06-24 已将运行时 Planner 从“能力缺口阻断”升级为动态航班/航铁混合接入：机场候选通过交通节点目录解析 IATA 后查询 Flight Offers，直飞和航班中转 offer 可生成 `DIRECT_FLIGHT` / `TRANSFER_FLIGHT`；当直达铁路和直达航班均不可用时，Planner 会尝试航班+铁路或铁路+航班的 Provider 事实组合，并仅在连接时间满足约束时生成 `FLIGHT_RAIL_MIXED`。
执行记录：2026-06-25 已修正航班 Provider 未启用时的失败语义：当航班报价 Provider 未启用或缺少配置时返回 `no enabled flight offer provider` 并归类为 `FLIGHT_PROVIDER_DISABLED`，不再误报为“无航班报价返回”。
执行记录：2026-07-04 已将航班 Provider 从旧航班报价校验链路迁移为 `airline_mu_public_query`、`airline_cz_public_query`、`airline_sc_public_query` 官方公开前端采集源：Provider 使用 `httpx`、源站 allowlist、每源限流、TTL 缓存、SQLite 原始快照和 canonical offer 索引；Planner 取消报价二次确认和按固定价差生成额外舱位的逻辑，只消费 Provider 返回的真实价格、真实舱位、可售状态和 evidence id；无可售、缺价、解析失败、源站不可用或未启用时写入 `SourceFailure` 并阻断航班方案，不做 fallback。
执行记录：2026-07-05 已完成国内客运航司官网技术确认台账 `docs/AIRLINE_OFFICIAL_SITE_TECH_CHECK_20260705.xlsx`：按航司逐行记录官网入口、匿名可达、robots、订票/航班查询入口、前端资源/API 线索、票价/航班时间/余票舱位字段线索、验证码/风控信号、是否可继续真实查询取样、Provider 建议和优先级；本次仅做入口层与前端资源层低频确认，不提交真实乘机人信息、不登录、不下单、不支付、不绕验证码。
执行记录：2026-07-05 已重新生成 `docs/AIRLINE_OFFICIAL_SITE_TECH_CHECK_20260705.xlsx`，修复 Windows Excel 2024 打开时中文显示为 `??` 的编码问题；当前 xlsx 内部 XML 已验证包含中文表头和航司名，且不含 `??` 残留。
执行记录：2026-07-15 航司独立技术契约从 3 套扩展到 10 套，覆盖 `airline_mu_public_query`、`airline_cz_public_query`、`airline_sc_public_query`、`airline_ca_public_query`、`airline_hna_micro_public_query`、`airline_zh_public_query`、`airline_3u_public_query`、`airline_9c_public_query`、`airline_ho_public_query`、`airline_qw_public_query` 共 16 个承运人代码；配置支持仅修改对应 `LICENSE_STATUS=APPROVED` 即自动启用并采用 1 QPS，但许可状态不能绕过匿名真实响应、动态材料、验证码/限流和字段契约的技术门禁。当前 10 套均保持 fail-closed，详细阻塞证据见 `docs/flight_provider_evidence/2026-07-15/expanded_airline_technical_review.md`。

任务：

- 使用官方公开航司采集 Provider 形成真实航班报价链路。
- 支持直飞、中转、多机场组合。
- 接入航班状态、天气、机场复杂度作为风险辅助。
- 跨航司、跨航站楼、重新安检、托运行李等风险结构化。

验收：

- 有自采 Provider 解析、缺价/无可售阻断、allowlist、Planner 阻断语义和 fixture 回归测试。
- 报价与可售状态标注数据来源、更新时间和最终平台确认提示。
- 航班核心事实缺失时不生成对应航班方案。

### P1-06 Candidate Plan Generator

状态：已完成（2026-06-12；同步候选池分层、硬约束过滤和 LLM 候选控制验收通过，异步增量体验继续归入 P2-02/P3-02）
执行记录：2026-06-27 已新增时间锚点与门到门 schedule 计算：`TravelRequest` 支持 `time_anchor_type`、`time_window_start`、`time_window_end`，Planner 会为接驳段反算 `departure_time`/`arrival_time`，并在重新规划时按主程出发窗口或最终到达约束过滤真实 Provider 返回的车次/航班候选；切换接驳方式后也会刷新整条方案时间线。

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

状态：已完成（2026-06-12）

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

状态：已完成（2026-06-12；真实 LLM 仍受 `real_llm` 授权阻塞）
执行记录：2026-06-27 已修复真实 LLM 推荐输出 schema 漂移问题：Recommendation Prompt 现在显式给出 `LLMRecommendationOutput` JSON 模板、允许/禁止字段和三类推荐 slot；当真实 LLM 返回 `recommendations` map、额外 `request_id` 或缺少 `selected_recommendations` 等 schema 错误时，推荐链路会进入一次 repair，而不是直接返回 `recommendation_result = null`。
执行记录：2026-06-29 已排查 Recommendation 合规性规则：当前 LLM Input 已传入 `candidate_plan_ids` 与 `candidate_plans`，Prompt/Repair Prompt 已约束只选候选池内方案；不合规仍可能来自模型输出 schema 漂移、照抄 JSON 模板占位符、选择候选池外 `plan_id`、选择不可推荐/阻断/过期方案或后端进程未重启导致读取旧 LLM 配置。后续如调整 Prompt，应避免把 `plan_id` 占位符写成可被模型原样复制的字符串，并补充失败审计展示。
执行记录：2026-06-29 已优化 Recommendation Prompt 与 Provider 用户消息：移除可被模型照抄的 `plan_id` 占位符 JSON 模板，在每次推荐/repair 请求中单独列出合法 `plan_id` 清单并要求逐字复制；同步更新 `LLM_PROMPT_DESIGN.md`，新增回归测试覆盖 Prompt 中真实 ID 列表与占位符移除，避免模型把说明文字当作 `plan_id` 输出。
执行记录：2026-06-29 已复盘真机异步任务 `job_e3d358d69688` 的 Recommendation 失败原因：`real_llm` 数据源配置为 OK，但完整 `candidate_plans` JSON 过大导致推荐调用 ReadTimeout。现已将发送给 LLM 的推荐输入改为 `LLMRecommendationSelectionInput` 摘要，仅包含 plan_id、成本、耗时、舒适度、风险、数据质量和主段信息；后端仍使用完整 TravelPlan 做输出校验。真实 LLM probe 验证 compact prompt 约 4.5k 字符、11.2 秒返回，schema/semantic 校验均通过。
执行记录：2026-07-07 架构侧已更新 Recommendation Prompt 设计口径：`LLMRecommendationOutput Schema V1.15` 仅作为后端校验契约，运行时 Prompt 应只提供最小输出字段契约、合法 `plan_id` 清单、候选摘要和自检规则；不得把完整 `TravelPlan`、完整 Schema 或可被照抄的 `plan_id` 占位符放入 LLM input。代码侧需同步 `recommendation_prompt_v1_0.txt`、Recommendation user prompt 和 repair prompt。

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

状态：已完成（2026-06-12）

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

状态：已完成（2026-07-04；12306、航司官网、地图和打车导航入口均保持 redirect-only，购票平台代理入口已移除）

任务：

- 完成 12306、航司官网、地图、打车跳转能力。
- 跳转请求不得携带登录、下单、支付、抢票参数。
- 每个 redirect 带 generated_at、expires_at、transaction_boundary、data_source。
- URL 不可用时返回 fallback_instruction。

验收：

- 覆盖 BR-001 至 BR-005、BRQ-001 至 BRQ-003。
- App 明确展示“跳转后以外部官方平台为准”。
- 不保存第三方账号、密码、cookie、token。

---

## 3. P2 任务：App 产品体验

### P2-01 App 信息架构

状态：已完成（2026-06-12：已完成底部双 Tab 信息架构与“云起 / 路明”闭环；云起承载空白 prompt 输入和输入校验，路明承载规划中、结果、方案详情、数据来源、错误、空结果、重算和 redirect-only 跳转；App 仍保持薄客户端，只调用后端 API；已更新 `frontend/ui-preview.html` 与 `frontend/ui-preview-screenshot.png`，并通过 App typecheck、API/Redirect 回归测试和本地预览截图验收。）

任务：

- 设计并实现首页/输入页、规划中页、结果页、方案详情页、数据来源页、错误页、空结果页。
- 保持薄客户端：App 不调用第三方交通数据源、不计算复杂路线、不调用 LLM。
- 移动端优先优化输入、卡片横滑、详情展开、重算和跳转。

验收：

- 用户能完成“输入需求 -> 查看推荐/候选 -> 调整方案 -> 跳转确认”的闭环。
- 错误、降级、空结果都有明确下一步。
- UI 不依赖硬编码样例数据。

### P2-02 规划中与异步任务体验

状态：已完成（2026-06-12：已新增 AsyncJob Schema、`/api/travel/plan/async` 启动接口、`/api/travel/jobs/{job_id}` 轮询接口和 `/api/travel/jobs/{job_id}/retry` 重试接口；App 提交流程已切换为异步启动 + 轮询，支持 RUNNING 首屏、PARTIAL/COMPLETE/FAILED 最终展示、失败源重试和改写需求入口；生产级队列、取消、超时与并发控制继续归入 P3-02。）
执行记录：2026-06-27 根据真机日志 `job_925b5a7146cf` 修复前端过早放弃轮询的问题：该次后端约 55 秒后返回 `PARTIAL + 4 个铁路直达候选 + PARTIAL_READY`，但 App 原先 30 次、约 36 秒即进入错误态并显示“规划失败”；现已将轮询窗口扩展到约 120 秒，避免真实 Provider/LLM 辅助链路较慢时误报失败。
执行记录：2026-06-27 已调整 App 规划中阶段进度展示：解析、地点、接驳、铁路、航班、评分、推荐改为指示灯样式；由于当前后端仅返回粗粒度 `progress` 与 `AsyncJob.job_status`，未提供逐阶段实时状态，前端只标记可确定完成的解析阶段，最终完成态才全量点亮，避免把 55% 等中间进度误展示为多个真实阶段已完成。
执行记录：2026-06-29 已替换 App 规划中页的环节指示灯：移除“解析、地点、接驳、铁路、航班、评分、推荐”文字阶段展示，改为抽象世界地图等待态；规划中固定全球国家/地区光点依次亮起，`progress >= 100` 时全部亮起，该动效不绑定用户起终点，也不伪装为后端逐阶段任务状态。
执行记录：2026-07-01 已修正规划中世界地图等待态的显示条件：结果页只要处于 `loading` 就展示地图，不再要求当前没有已有方案，避免在已有结果上重新规划、重试来源或调整时间时继续显示旧结果而看不到地图；同时为地图区域增加最小高度并提高陆地对比度。
执行记录：2026-07-01 已将规划中页地图底图从前端 View 拼接的抽象大陆块替换为项目内 PNG 世界地图资产 `frontend/assets/maps/world-map.png`，保留固定全球国家/地区光点依次亮起的等待动效，提升用户对“世界地图”的识别度。
执行记录：2026-07-01 已根据体验反馈改用搜索引擎获取的真实地图素材：`world-map.png` 替换为 Ultimaps 免费世界地图 PNG，并新增 `frontend/assets/maps/ATTRIBUTION.md` 记录来源、授权说明和本地裁剪处理；前端不再使用手工生成或拼接的地图底图。
执行记录：2026-07-01 已按地图原有边界线调整规划中高亮效果：移除圆圈点位高亮，新增 `frontend/assets/maps/highlights/*.png` 区域蒙版，规划中按北美洲、南美洲、欧洲、非洲、亚洲、大洋洲依次对地图陆地区域染色，完成态展示全部区域高亮。
执行记录：2026-07-01 已在开发模式下为规划中世界地图加入临时高亮诊断区：单独渲染当前区域透明蒙版并监听 `onLoad/onError`，同时用显式 `zIndex` 渲染底图 + 蒙版叠层，用于区分 Expo Go 资产缓存问题与透明 PNG 叠层渲染问题。
执行记录：2026-07-01 已根据真机诊断结果修正规划中主地图图层：左右诊断图均可显示，确认 Expo Go 已加载 `highlights/*.png` 且透明 PNG 蒙版可渲染，问题定位为主地图 `ImageBackground` 子层未在当前渲染链路显示；主地图已改为显式 `View + Image` 分层，底图 `zIndex: 0`、区域蒙版 `zIndex: 1`，不采用整图切换方案。
执行记录：2026-07-02 已调整规划中世界地图视觉与资产：主地图海洋底色改为与诊断预览一致的深色；底图和全部区域蒙版统一裁掉底部透明留白与水印区域，保留地图来源说明到 `frontend/assets/maps/ATTRIBUTION.md`；亚洲蒙版移除东南角像素，避免与大洋洲阶段产生重复观感，并删除未使用的 `states/` 整图帧资产以保持不采用图片切换方案。
执行记录：2026-07-02 已优化规划中世界地图等待态：移除开发诊断区和顶部文字进度；高亮从区域轮播改为左到右逐步覆盖的水流式体验进度，0%-30% 快速推进、30%-80% 慢速推进、80%-95% 更慢并封顶等待，请求完成后直接跳到 100%；高亮蒙版改为青绿色并去除黄色观感，该进度仅用于等待体验，不展示为后端真实阶段。
执行记录：2026-07-02 已修正水流式高亮实现：移除可见的矩形扫光边和分区蒙版叠加，新增 `frontend/assets/maps/world-map-flow.png` 单张全陆地透明蒙版，非陆地像素保持透明，左到右裁剪时只会让世界地图空白陆地区域逐步变色，覆盖像素与底图陆地像素一致且不显示矩形块。
执行记录：2026-07-02 已回收水流式高亮的过度装饰：移除 30 条水平切片、水波圈和由切片造成的扫描条纹，恢复为单张全陆地透明蒙版左到右覆盖；仅保留同一蒙版的极低透明光晕层，避免出现矩形块、横向条带和噪声装饰。

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

状态：已完成（2026-06-12：方案详情页已展示时间线、费用明细、估算标记、风险提示、舒适度拆解、数据完整度/置信度、最新数据更新时间、数据来源、票源增强等级与限制，以及航班中转/多机场/前序风险缺失边界；相关文案避免“保证有票/一定成功”等交易承诺，并已更新 UI 预览截图。）
执行记录：2026-06-27 根据真机体验反馈收敛方案详情展示：前端已隐藏“可信解释”“提醒”“舒适度拆解”“风险提示/航班风险边界”等区块，保留时间线、费用明细、可调整选项、票源增强和数据来源页；后端仍保留数据质量、舒适度和风险结构化字段供后续产品展示或诊断使用。
执行记录：2026-06-27 已补充方案时间线中的具体时间点展示：当铁路/航班段包含 `departure_time` 和 `arrival_time` 时，前端会显示类似 `高铁 · 06:01 - 21:53 · 15小时52分`，接驳段继续显示方式与耗时。
执行记录：2026-06-27 已把接驳段纳入具体时间点展示：后端根据铁路提前 20 分钟、航班提前 90 分钟、到站/落地后缓冲反算本地接驳时刻；App 方案详情页新增紧凑的“主程出发/最晚到达 + HH:mm”重新规划入口，用户调整时间会重新提交 TravelRequest 并重新查询 Planner，而不是前端本地改写旧方案。
执行记录：2026-06-28 已将时间调整入口从自定义 `HH:mm` 文本输入改为双列滑轮式选择器：用户通过小时/分钟列选择“预估出发”或“最晚到达”的时间后再触发重新规划，避免移动端手输格式错误。
执行记录：2026-06-28 已将时间滑轮从结果页内联展示改为点击当前时间值后弹出底部时间选择弹窗；结果页只保留时间值与重新规划按钮，减少页面纵向占用。

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

状态：已完成（2026-06-12：已新增 `frontend/src/designSystem.ts` 管理颜色、间距、圆角、触控热区和内容宽度；App 已接入宽屏内容约束、关键操作 accessibilityRole/accessibilityLabel、触控 hitSlop 与 44px 级最小触控尺寸；风险状态保留文字标签，不只依赖颜色。）
执行记录：2026-06-27 时间调整 UI 采用 8px 圆角、44px 触控热区、分段控件和紧凑输入行，放在推荐方案与详情之间，避免把时间调整入口做成大块说明卡或打断时间线阅读。
执行记录：2026-06-28 时间调整 UI 已替换为固定高度小时/分钟滑轮，保留 44px 触控项、选中态和屏幕阅读器 label；去除该处自定义时间输入框，减少小屏键盘遮挡与格式校验成本。
执行记录：2026-06-28 时间选择器已改为透明遮罩 + 底部弹窗模式，支持点击当前时间打开、点击遮罩/关闭按钮退出、确认后更新显示时间；页面内不再常驻滑轮，降低与方案卡片的视觉冲突。

任务：

- 建立颜色、字体、间距、按钮、卡片、表单、状态标签、风险标签组件。
- 适配小屏、大屏、动态字体、安全区域、横竖屏策略。
- 增加无障碍 label、触控区域、颜色对比。

验收：

- 核心页面在主流移动屏幕不重叠、不截断。
- 关键操作可被屏幕阅读器理解。
- 风险状态不只依赖颜色表达。

### P2-05 App 原生能力

状态：已完成（2026-06-12：已新增 `frontend/src/nativeCapabilities.ts`，支持系统定位权限请求与手动输入降级、外部 App/系统 URL 跳转封装、分享方案、复制行程摘要、保存最近一次脱敏方案快照，以及 App 回到前台后轮询未完成任务或提示 redirect 过期；未保存第三方账号、cookie、token、支付或实名信息。）

任务：

- 支持系统定位权限请求和定位失败降级。
- 支持打开地图、航司、12306、打车平台的外部 App 或系统外部跳转入口。
- 支持分享方案、复制行程摘要、保存最近一次规划。
- 支持 App 后台恢复后刷新过期方案状态。

验收：

- 权限拒绝时 App 可继续手动输入地点。
- 外部跳转失败时有 fallback_instruction。
- 最近规划不保存第三方账号、支付或实名敏感信息。

### P2-06 用户反馈和问题上报

状态：已完成（2026-06-12：结果详情页已提供“路线不准 / 价格不准 / 跳转失败 / 看不懂”反馈入口；后端新增 `/api/feedback`，反馈关联 request_id、trace_id、correlation_id、plan_id、source_id，并在内存中按 category/source 聚合计数；后端拒绝包含账号、密码、cookie、token、支付、实名等敏感内容的反馈。）

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

状态：部分完成（2026-06-12：已新增持久化层 `backend/app/services/persistence.py` 和 TTL 缓存层 `backend/app/services/cache_store.py`；本地默认使用 SQLite 保存 TravelPlanResponse、TravelPlan 快照和反馈，支持清空内存索引后按 plan_id 读取短期方案详情；缓存层保存异步任务和重算幂等结果并定义 TTL。PostgreSQL 持久化与 Redis 缓存尚未实现，当前不提供对应运行配置。）

任务：

- 引入 PostgreSQL 保存用户请求、TravelRequest、TravelPlan 快照、Provider 调用日志、LLM 调用摘要、反馈。
- 引入 Redis 缓存地点解析、站点/机场候选、路线估算、Provider token、异步任务状态。
- 定义 TTL、失效策略和数据版本。

验收：

- 服务重启后可查询短期方案详情。
- 缓存命中不破坏 DataSourceMetadata。
- 敏感字段不落库或已脱敏。

### P3-02 异步任务与队列

状态：已完成（2026-06-12：异步规划已支持 job_id、job_status、polling_url、幂等键复用、重试和取消入口；App 可取消当前规划；新增 `task_queue.py` 管理任务超时、Provider 超时、重试次数和最大并发配置项；异步状态符合 AsyncJob Schema，状态缓存有 TTL。）

任务：

- 为长耗时规划引入任务队列。
- 支持 job_id、job_status、polling_url、取消和超时。
- Provider 调用并发控制、超时、重试、fallback 策略配置化。

验收：

- 单个 Provider 慢不拖垮全部规划。
- 重复请求受 idempotency_key 控制。
- 任务状态符合 AsyncJob Schema。

### P3-03 可观测性

状态：已完成（2026-06-12：已新增 `backend/app/services/observability.py`，按 TravelPlanResponse 聚合请求量、COMPLETE/PARTIAL/FAILED 状态、Provider 失败、LLM repair 指标；新增只读 `/api/observability/metrics` 端点，输出 request/trace/correlation 可串联的统计快照，且不记录第三方账号、token、支付或实名信息。）

执行记录：2026-07-04 已新增统一后端文件日志配置 `backend/app/core/logging.py`：启动时按时间生成 `logs/backend-YYYYMMDD-HHMMSS.log`，默认单文件上限 100MB，写满后自动创建新的时间命名日志文件；HTTP middleware 记录 method、path、status、duration、request_id、trace_id、correlation_id、device_id，不写入请求体、第三方账号、token、支付或实名信息；`.env.example` 已补充日志开关、目录、前缀、级别和大小配置。

执行记录：2026-07-04 已补齐高铁数据流转关键节点日志：Planner 记录铁路规划开始、站点候选、站点对、直达/中转/航铁混合查询、空结果/限流、方案创建和阻断原因；`rail_12306_public_query` Provider 记录配置启用、站名电报码解析、TTL cache 命中/未命中、12306 init/queryG 请求响应、结果行数、席别票价过滤、offer 生成和 Provider 失败，便于按 request_id/source_id 串联调试。

任务：

- 结构化日志统一输出 request_id、trace_id、correlation_id、source_id、failure_class、message。
- 增加 metrics：请求量、成功率、PARTIAL 率、Provider 延迟、Provider 失败率、LLM 修复率。
- 增加告警：核心 Provider DOWN、错误率异常、推荐不可用率异常。

验收：

- 一次用户请求可串联 API、Provider、LLM、App 反馈。
- 不记录第三方账号、token、支付或实名敏感信息。

### P3-04 鉴权、限流与安全

状态：已完成（2026-06-12：已新增 `backend/app/core/security.py`，支持匿名设备标识 `x-device-id`、可选 API Key 闸门、请求体大小限制、每设备分钟级限流，并在响应头回传 request_id/trace_id/correlation_id/device_id；`.env.example` 已补充安全配置项，公共异常仍返回脱敏 ErrorResponse。）

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

状态：已完成（2026-06-12：已新增 `.github/workflows/ci.yml`，覆盖 schema 导出/diff、后端测试、App typecheck 和 Expo export；已新增 `docs/RELEASE_CHECKLIST.md` 与 `docs/ROLLBACK_CHECKLIST.md`，包含 staging/production 配置、Provider 授权、iOS/Android 构建验证、发布记录和回滚步骤；本地已验证后端 111 个测试、App typecheck 和 `npm run build`。）

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

状态：已完成（2026-06-12：已新增只读 `/api/admin/data-sources`，复用 DataSourceRuntimeStatus 输出数据源健康、授权、最近失败、降级原因和平均延迟等字段；接口不暴露 qps_limit、密钥或 Provider 凭证，可供运营/开发判断当前能力可用性。）

任务：

- 展示数据源健康、授权状态、最近失败、平均延迟、降级原因。
- 支持只读查看 DataSourceRuntimeStatus。
- 生产配置变更必须走审核，不在后台直接暴露密钥。

验收：

- 运营能判断当前哪些能力可用。
- 开发能定位 Provider 失败趋势。

### P4-02 搜索与规划质量评估

状态：已完成（2026-06-12：已新增 `docs/GOLDEN_ROUTES.json` 和 `scripts/evaluate_quality.py`，输出方案覆盖率、PARTIAL 状态、推荐可用性和 pass_rate；默认模式只报告质量指标，`--strict` 可作为门禁；当前未授权真实核心 Provider 的 DEV 配置下 pass_rate 为 0.3333，反映真实能力边界。）

任务：

- 建立 golden route 集合。
- 记录方案覆盖率、推荐可用率、PARTIAL 率、用户选择率、跳转成功率。
- 为价格、耗时、风险和舒适度建立离线评估。

验收：

- 每次算法/Provider 改动可比较质量变化。
- 有可量化指标判断是否接近产品级。

### P4-03 多城市、多语言和个性化

状态：已完成（2026-06-12：规则解析器已支持北京/广州、上海/青岛、成都/深圳、杭州/西安等多城市候选族，并新增英文/中英混合输入的城市对和偏好词解析，如 `from Beijing to Guangzhou, comfortable, train only`；App 已保存最近一次脱敏方案快照和用户偏好入口，个性化不覆盖 hard constraints。）

任务：

- 扩展城市和交通模式覆盖。
- 支持英文或中英混合输入。
- 引入用户偏好记忆，但不得保存敏感第三方账号信息。

验收：

- 新城市接入无需改 Planner 硬编码。
- 个性化不会越过 hard constraints 和安全边界。

### P4-04 App 增长与留存

状态：已完成（2026-06-13：App 已将最近规划从单条快照升级为 5 条脱敏历史摘要，并新增收藏方案、行程提醒、价格/状态变化关注、常用出发地与目的地偏好记忆；所有收藏、提醒和偏好均可在 App 内关闭或移除，关闭偏好时会清空对应本地字段；新增增长事件 `RECENT_PLAN_VIEWED`、`FAVORITE_TOGGLED`、`TRIP_REMINDER_TOGGLED`、`PRICE_STATUS_WATCH_TOGGLED`、`PREFERENCE_UPDATED`，并复用 `/api/events` 将输入、规划成功、PARTIAL、推荐点击、跳转、反馈等事件按 request_id/trace_id/plan_id 脱敏关联到 `/api/observability/metrics`；事件 metadata 只保留非敏感字段并拒绝账号、token、支付、实名等内容。）

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
