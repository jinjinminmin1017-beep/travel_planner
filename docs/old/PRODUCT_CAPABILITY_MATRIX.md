# 产品能力矩阵

更新日期：2026-07-19

本文档是当前可演示能力、真实 Provider 边界、自动化 fixture 边界和 Planner 路线覆盖范围的单一判断入口。新增 Provider、规划能力、降级策略或 App 可见能力时，必须同步更新本文件。

## 状态图例

| 状态 | 含义 |
|---|---|
| 验收通过 | 已有代码、配置、测试或 CI 证据，可作为当前演示能力使用。 |
| 进行中 | 已有部分实现，但产品边界、真实数据覆盖或体验闭环尚未完整验收。 |
| 阻塞于授权 | Adapter 或接口形态已准备，但缺少用户自有凭证、商务授权、合作方模板或生产许可。 |
| 待实现 | 尚未进入可演示实现。 |
| 自动化专用 | 只允许在测试中使用，不得作为运行时 fallback 或真实交通事实。 |

## 产品能力矩阵

| 能力 | 当前状态 | 可演示范围 | 不可承诺或下一步 |
|---|---|---|---|
| Expo / React Native App 工程 | 验收通过 | App 入口、README、类型检查和本地 API Base URL 配置已收口。 | 尚未完成完整 App 产品体验与发布流水线。 |
| Schema V1.15 合同 | 验收通过 | 后端 Pydantic、导出 JSON Schema、前端类型与主要枚举已对齐。 | 新字段或枚举必须重新导出 schema 并补测试。 |
| API 错误与降级语义 | 验收通过 | `SourceFailure`、`MissingPlanExplanation`、`missing_components`、PARTIAL/FAILED 响应可被 App 展示。 | 异步任务、重试队列和生产级监控仍待 P2/P3 推进。 |
| Provider 配置与 CI 安全档位 | 验收通过 | CI 区分 fixture 测试、公开只读 smoke、密钥 Provider smoke；生产环境禁止启用未授权数据源。 | 有密钥 Provider 只有在 secrets 存在时跑 smoke。 |
| 产品能力矩阵 | 验收通过 | 本文件列出产品、开发、测试可判断的当前能力与边界。 | 每次新增 Provider 或规划能力必须同步更新。 |
| LLM Intent Parser | 验收通过 / Prompt 待按 V1.2 口径精简 | 已有 Prompt 模板、版本常量、真实 LLM wrapper、一次 repair、语义校验、规则 fallback、LLM 调用审计日志和缺信息追问；架构口径要求 Prompt 只提供最小字段契约与关键枚举，`TravelRequest Schema V1.15` 仅作为后端校验契约。 | `real_llm` 默认禁用时使用规则 fallback；真实 LLM 仍需用户自有 key 与授权后才能启用；不得把完整设计文档或完整 Schema 发送给 LLM。 |
| 地点解析与节点候选 | 验收通过 | `location_resolver` 已集中管理地点解析、站点候选、机场候选、候选元数据和 Nominatim fallback；Planner 不再维护坐标表。 | 路线规划引擎仍只覆盖已实现城市对；未覆盖城市对会返回清晰不可用和候选节点说明。 |
| 本地接驳 | 验收通过 | `local_transfer_engine` 已支持 TAXI、SUBWAY、BUS、WALK 可用性判断；真实地图 Provider 返回距离、耗时、费用估算；地图不可用时以 `SourceFailure` 标记并退回内部规则估算；App 可展示接驳上下车/换乘说明并切换重算。 | 完整逐站公交/地铁线路、打车平台实时派单和生产级导航仍依赖授权地图或打车 Provider。 |
| 铁路规划 | 12306 公开查询 Provider 已接入 / 票源增强待动态化 | Planner 已可按地点解析出的候选站点生成站点对查询，并仅用 `rail_12306_public_query` 返回的真实车次、时刻、席别和票价组装铁路方案；座席必须同时满足可用和有票价，余票字段只用于后端筛选且 App 不展示；`rail_12306_redirect` 可跳转官方入口。 | 多段和票源增强仍按能力缺口阻断且不使用旧模板补造；缺站点码、无票、缺价、限流或页面结构变化时必须阻断对应铁路方案；测试 fixture 不得作为运行时 fallback。 |
| 航班规划 | 自采 Provider 已接入 / 源站审批后启用 | `flight_planning_engine` 已覆盖直飞、中转、多机场组合；Planner 使用 10 套独立官方公开航司契约覆盖 16 个承运人代码，只有真实价格、真实舱位和可售信号均通过技术契约且许可已审批时才生成航班段；OpenSky/天气仅作为风险辅助边界。 | 未启用、未审批、技术契约不完整、源站不可用、缺价、无可售信号或解析失败时必须阻断对应航班方案；不得用 fixture、OpenSky、估算价、报价二次确认假设或按固定价差生成额外舱位作为 fallback。 |
| 候选方案生成 | 验收通过 | `candidate_generator` 已分层管理原始方案和 LLM 候选池，支持 1-15 条可验证候选、hard constraints 过滤、soft preference 排序/排除，并为被过滤方案生成 MissingPlanExplanation。 | 异步增量候选体验和任务队列仍归入 P2-02/P3-02；不得为凑满候选数量补造方案。 |
| Cost / Comfort / Risk | 验收通过 | `cost_comfort_risk_engine` 已独立输出 Money 汇总、ComfortScore breakdown/score_vector/score_version、RiskAssessment/RiskItem 和 DataQuality 缺失/警告/置信度；重算路径复用同一费用引擎。 | 后续质量优化可继续细化权重和离线评估，但 LLM 不参与事实计算。 |
| LLM Recommendation | 验收通过 / 真实 LLM 阻塞于授权 / Prompt 待按 V1.2 口径精简 | Recommendation Prompt、语义校验 REC-001 至 REC-012、一次 Repair Prompt、LLMValidationResult 元数据和候选池外/不可选/BLOCKED/过期方案拒绝链路已完成；架构口径要求运行时只传候选摘要、合法 `plan_id` 清单和最小输出契约。LLM 不可用时返回 `recommendation_result = null`，候选仍可展示。 | `real_llm` 缺用户自有 key 和授权前不得宣称真实 LLM 推荐上线；不得用代码 fallback 生成三张推荐卡；不得在 Prompt 模板中放可被照抄的 `plan_id` 占位符。 |
| Recalculate 交互 | 验收通过 | 支持座席、舱位、本地接驳选项的局部重算，返回费用/耗时/舒适度 delta；支持 idempotency_key 幂等缓存，并在 `PLAN_AND_RECOMMENDATION` / `FULL_REEVALUATION` 范围内重跑推荐。 | App 局部刷新体验仍需 P2 页面闭环承载。 |
| Redirect-only Handoff | 验收通过 | 12306、航司官网、高德/百度地图与打车导航入口均走 redirect-only；每个 redirect 带 generated_at、expires_at、transaction_boundary、DataSourceMetadata，URL 安全检查会阻断登录/下单/支付/抢票参数并返回 fallback_instruction。 | 只跳转，不登录、不下单、不支付；跳转失败只给人工操作说明，不拼接替代购票链接。 |
| App 信息架构 | 验收通过 | 已形成底部双 Tab：云起承载空白 prompt 输入和输入校验，路明承载规划中、推荐、候选、详情、数据来源、错误、空结果、重算与 redirect-only 跳转；`frontend/ui-preview.html` 与截图已同步。 | 生产级队列、后台恢复和发布级原生能力仍需 P2-05/P3-02 继续推进。 |
| 异步任务与队列 | 验收通过 | `AsyncJob` Schema、异步规划启动、轮询状态、失败源重试、取消、幂等键复用和 App 规划中体验已完成；RUNNING 首屏可先返回，PARTIAL/COMPLETE/FAILED 可轮询展示，状态缓存有 TTL。 | 当前为应用内任务执行器；分布式 worker、跨实例锁和生产级队列监控仍需部署层补齐。 |
| 方案详情可信解释 | 验收通过 | App 详情页展示时间线、费用明细、估算标记、风险提示、舒适度拆解、数据完整度/置信度、最新数据更新时间、数据来源、票源增强等级与航班中转风险边界。 | 只解释已由后端结构化输出或授权数据源提供的事实；不承诺余票数量、可售交易结果、下单成功或外部平台实时状态。 |
| App 设计系统与可访问性 | 验收通过 | `frontend/src/designSystem.ts` 集中管理颜色、间距、圆角、触控热区和内容宽度；关键按钮、Tab、推荐卡、候选卡和重试/跳转入口已有 accessibilityRole/accessibilityLabel，触控区域满足移动端操作。 | 后续新增页面或原生能力必须复用 token 和辅助标签；完整屏幕阅读器人工验收仍需真机发布前执行。 |
| App 原生能力 | 验收通过 | `nativeCapabilities` 支持定位权限请求与手动输入降级、外部 App/系统 URL 跳转封装、分享方案、复制行程摘要、最近一次脱敏方案快照，以及 App 回到前台后刷新未完成任务或提示 redirect 过期。 | 未接入 `expo-location` 的平台只做权限/降级提示；最近方案仅保存脱敏摘要，不保存第三方账号、cookie、token、支付或实名信息。 |
| 用户反馈和问题上报 | 验收通过 | App 详情页提供路线不准、价格不准、跳转失败、看不懂反馈入口；后端 `/api/feedback` 关联 request_id、trace_id、correlation_id、plan_id、source_id 并按 category/source 聚合计数。 | 反馈内容不得包含第三方账号、cookie、token、支付或实名信息；当前聚合为内存实现，生产持久化归 P3-01/P3-03。 |
| 持久化与缓存 | 验收通过 / 外部 PostgreSQL 与 Redis 需部署配置 | 本地默认 SQLite 持久化 TravelPlanResponse、TravelPlan 快照和反馈；清空内存后可按 plan_id 读取短期方案详情；TTL 缓存保存异步任务和重算幂等结果；`.env.example` 已提供 PostgreSQL/Redis 配置入口。 | 当前测试覆盖本地持久化和内存 TTL；生产 PostgreSQL/Redis 需要运行时依赖、DSN、Redis URL、备份和运维策略。 |
| 可观测性 | 验收通过 | `observability.py` 聚合请求量、规划状态、Provider 失败和 LLM repair 指标；`/api/observability/metrics` 提供只读快照，继续保留 request_id/trace_id/correlation_id 串联。 | 当前为进程内指标，生产告警、Prometheus/OpenTelemetry 导出和跨实例聚合仍需部署层接入。 |
| 鉴权、限流与安全 | 验收通过 | `security.py` 支持匿名设备标识、可选 API Key、请求体大小限制、每设备分钟级限流；响应头回传 request_id/trace_id/correlation_id/device_id，异常继续走脱敏 ErrorResponse。 | 生产密钥轮换、证书绑定、WAF 和安全审计需部署层执行；默认 DEV 不强制 API Key。 |
| 发布流水线 | 验收通过 | `.github/workflows/ci.yml` 覆盖 schema 导出/diff、后端测试、App typecheck 和 Expo export；`RELEASE_CHECKLIST.md` 与 `ROLLBACK_CHECKLIST.md` 覆盖 staging/production、iOS/Android 验证、发布记录与回滚。 | 真正商店签名、内测分发和生产部署仍需组织账号、证书和发布权限。 |
| 数据源运营后台 | 验收通过 | `/api/admin/data-sources` 提供只读 DataSourceRuntimeStatus，展示健康、授权、降级原因、最近失败和延迟字段，不暴露密钥。 | 配置变更仍需走代码/环境变量审计流程，不在后台直接编辑生产 Provider。 |
| 搜索与规划质量评估 | 验收通过 | `docs/GOLDEN_ROUTES.json` 与 `scripts/evaluate_quality.py` 可输出 golden route 覆盖率、PARTIAL 率、推荐可用性和 pass_rate，默认不阻塞、`--strict` 可门禁。 | 当前 DEV 未授权真实核心 Provider 时 pass_rate 会反映能力缺口，不可把 fixture 覆盖率当作真实上线质量。 |
| 多城市、多语言和个性化 | 验收通过 | 规则解析支持北京/广州、上海/青岛、成都/深圳、杭州/西安候选族，以及英文/中英混合城市对和偏好词；App 保存最近一次脱敏方案快照。 | 新城市仍需 Location Resolver 与规划引擎覆盖或清晰降级；个性化不得越过 hard constraints。 |
| App 增长与留存 | 验收通过 | App 保存最多 5 条最近规划脱敏摘要，支持收藏方案、行程提醒、价格/状态变化关注、常用出发地和目的地偏好记忆；收藏、提醒和偏好均可关闭或移除。`/api/events` 覆盖输入、规划成功、PARTIAL、推荐点击、跳转、反馈以及留存事件，并在 `/api/observability/metrics` 中按 request_id/trace_id/plan_id 暴露脱敏事件索引。 | 提醒和价格/状态关注只保存本地脱敏关注项，不承诺后台推送、实时票价监控、可售状态或第三方平台交易结果；事件 metadata 不得包含第三方账号、支付、实名或凭证信息。 |

## Provider 能力矩阵

| source_id | 类型 | 当前状态 | 默认运行时 | 允许用途 | 不允许用途 |
|---|---|---|---|---|---|
| `internal_calc` | INTERNAL_CALCULATION | 验收通过 | 启用 | 确定性费用汇总、风险汇总、规则降级说明和接驳估算。 | 伪装成真实 Provider 返回票价、余票、航班或外部路线事实。 |
| `osrm_route` | MAP | 验收通过 | 启用 | 公开只读路线距离/耗时 smoke 与低频演示。 | 商业生产高频依赖公共实例。 |
| `nominatim_geocode` | MAP | 验收通过 | 启用 | 公开只读地点解析 smoke，低频调用并设置 User-Agent。 | 作为无限量生产地理编码服务。 |
| `amap_geocode` | MAP | 阻塞于授权 | 禁用 | 使用用户自有高德 Web Service key 进行地址地理编码。 | 未授权启用、提交真实 key 或把空结果改成规则坐标。 |
| `amap_place_search` | MAP | 阻塞于授权 | 禁用 | 地址解析不足时按城市执行高德 POI 关键字搜索。 | 同名候选不经消歧直接选择第一条。 |
| `open_meteo_forecast` | WEATHER | 验收通过 | 启用 | 天气风险辅助。 | 提供交通票价、余票、路况或交易承诺。 |
| `opensky_states` | FLIGHT | 验收通过 | 启用 | 航班动态/空域风险辅助。 | 提供航班报价、余票或可售状态。 |
| `rail_12306_public_query` | RAIL | 验收通过 | 启用 | 低频调用 12306 公开匿名查询能力，返回可验证的车次、时刻、可用席别和票价。 | 登录、绕验证码、逆向签名/加密、占票、下单、支付、抢票、展示余票数量或作为高频商用爬取能力。 |
| `rail_12306_redirect` | RAIL | 验收通过 | 启用 | 跳转到 12306 官方入口，用户自行确认。 | 自动登录、抢票、占票、下单、支付。 |
| `airline_official_redirect` | FLIGHT | 验收通过 | 启用 | 跳转到航司官网，用户自行确认。 | 代填敏感账号、自动下单或支付。 |
| `amap_uri_redirect` | MAP | 验收通过 | 启用 | 高德地图 URI 跳转。 | 绕过平台规则调用未授权商业路线 API。 |
| `amap_route` | MAP | 阻塞于授权 | 禁用 | 拿到用户自有 key 和授权后用于真实路线规划。 | 未授权时启用、商业使用或静默 fallback。 |
| `baidu_map_route` | MAP | 阻塞于授权 | 禁用 | 拿到用户自有 key 和授权后作为地图路线 Provider。 | 未授权时启用、商业使用或静默 fallback。 |
| `baidu_uri_redirect` | MAP | 阻塞于授权 | 禁用 | 授权确认后作为百度地图 URI 跳转备选。 | 未审核前在生产启用。 |
| `airline_mu_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 源站审核通过后低频采集东航官方公开前端报价，只返回有真实价格且有可售/余票信号的舱位。 | 登录、绕验证码、逆向强认证、下单、支付、抢票、缺价补价、无可售信号时生成航班方案或作为 fallback。 |
| `airline_mu_browser_query` | FLIGHT | 进行中 / 阻塞于授权 | 禁用 | 独立 Playwright worker 复用东航匿名浏览器会话，只把匹配本次查询且通过严格校验的航班、时刻、舱价和可售信号转换为 `FlightOffer`。 | 未完成许可、结果页模板确认、目标环境 Chromium 验收和 50 次 benchmark 前启用；不得绕验证码、保存 Cookie/指纹/Token、把挑战或结构变化当作空航班。 |
| `airline_cz_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 源站审核通过后低频采集南航官方公开前端报价，只返回有真实价格且有可售/余票信号的舱位。 | 登录、绕验证码、逆向强认证、下单、支付、抢票、缺价补价、无可售信号时生成航班方案或作为 fallback。 |
| `airline_sc_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 源站审核通过后低频采集山航官方公开前端报价，只返回有真实价格且有可售/余票信号的舱位。 | 登录、绕验证码、逆向强认证、下单、支付、抢票、缺价补价、无可售信号时生成航班方案或作为 fallback。 |
| `airline_ca_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 国航独立契约；许可审批后仍须通过匿名真实库存响应技术门禁。 | 不得把官网入口可达等同于可执行票价契约。 |
| `airline_hna_micro_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 海航微服务体系独立契约，覆盖 JD/8L/UQ/FU/Y8。 | 不生成或绕过动态密文、指纹、验证码和频控材料。 |
| `airline_hu_public_query` | FLIGHT | 验收通过 | 启用 | 海航官网匿名 deep-link 会话查询，解析 HU/Y8 等同站销售航班的真实含税总价和舱位。 | 不登录、不绕验证码、不持久化动态会话或长加密材料。 |
| `airline_zh_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 深航独立契约；许可审批后仍须通过匿名真实库存响应技术门禁。 | 不得把 B2C 入口可达等同于可执行票价契约。 |
| `airline_3u_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 川航独立契约。 | 不绕过 Dingxiang CAPTCHA/ConstID 等风险控制。 |
| `airline_9c_public_query` | FLIGHT | 验收通过 | 启用 | 春秋航空官网匿名公开航班、票价和舱位查询。 | 不登录、不绕验证码、不下单或支付。 |
| `airline_ho_public_query` | FLIGHT | 阻塞于授权 | 禁用 | 吉祥航空独立契约；已记录查询 endpoint 与 `INVALID_TOKEN` 匿名响应。 | 不伪造 token、blackBox 或绕过 Geetest。 |
| `airline_qw_public_query` | FLIGHT | 验收通过 | 启用 | 青岛航空官网匿名初始化与公开前端请求算法，返回真实航班、票价和舱位 JSON。 | 不登录、不绕验证码、不复用浏览器 Cookie、不下单或支付。 |
| `variflight_status` | FLIGHT | 阻塞于授权 | 禁用 | 授权后提供商业航班状态/延误风险。 | 未授权时调用或把 OpenSky 结果冒充商业状态。 |
| `real_llm` | LLM | 阻塞于授权 | 禁用 | 用户自有 key 存在时做解析、推荐选择和解释，并经过 Schema/语义校验。 | 生成车次、航班、价格、余票、路线、购买链接等事实字段。 |

处于“阻塞于授权”且没有可执行 adapter 的航司查询与 VariFlight 仅作为能力待办记录，不进入 `TRAVEL_DATA_SOURCE_IDS`、adapter 运行注册表或 `.env.example`。东航 `airline_mu_browser_query` 已有独立 worker adapter，但因真实验收未完成而以禁用状态进入注册表；春秋、海航和青岛航空已完成实现与审批，并通过代码、配置、测试和在线验收的同一次变更登记。

## 自动化 Fixture 边界

| 位置 | 状态 | 用途 | 运行时边界 |
|---|---|---|---|
| `backend/app/tests/conftest.py` | 自动化专用 | 用 `monkeypatch` 注入 fake flight/map/rail provider，保证 pytest 可稳定覆盖规划路径。 | 不得复制到业务路径；不得作为 Provider 失败后的运行时 fallback。 |
| `backend/app/tests/test_no_simulated_fallback.py` | 验收通过 | 验证地图 Provider 空结果时会标记 `SourceFailure` 并仅以 `internal_calc` 做明示降级。 | 不允许静默伪造真实地图路线。 |
| `.env.example` | 自动化专用 | 由测试夹具注入安全默认的 ENV-only DataSourceSettings，只包含已有运行消费者的字段。 | 不代表生产授权状态，不得被产品文案解读为真实可售能力。 |
| `backend/app/tests/*_providers.py` | 自动化专用 | 使用 fake HTTP client 映射 Provider 响应结构。 | 只验证 Adapter 解析逻辑，不证明外部服务实时可用。 |
| `frontend/ui-preview.html` 与 `frontend/ui-preview-screenshot.png` | 自动化专用 | App 输入、规划中、结果详情、数据来源、错误和空结果状态的视觉预览。 | 不作为运行时数据来源，不代表真实规划结果或外部平台实时可用。 |

运行时允许的降级只能是业务可解释的降级：例如地图 Provider 不可用时记录 `SourceFailure`、`missing_components=["map_route"]`，并把接驳段数据源标为 `internal_calc`。铁路、航班等核心事实缺失时必须阻断对应方案类型，不能用测试 fixture 补齐。

## Planner 路线覆盖与边界

| 路线或场景 | 当前覆盖 | 真实能力边界 |
|---|---|---|
| 上海嘉定南翔格林公馆 -> 青岛金水假日酒店 | 运行时覆盖动态铁路直达、中转铁路和接驳切换；铁路车次、时刻、席别和票价来自 `rail_12306_public_query`，多段中转、航班直飞、航班中转、航班多机场、航铁混合、票源增强在事实缺失时返回能力缺口说明，不输出旧模板方案。 | 地点/节点由 Location Resolver 管理；铁路方案必须同时验证有可用席别和票价，App 不展示余票状态或数量；航班方案依赖已审批的官方公开航司采集源返回真实价格和可售信号。 |
| 北京国贸 -> 广州天河体育中心 | 运行时覆盖非上海/青岛样例的动态铁路直达候选，避免复用上海虹桥/青岛北等硬编码结果。 | 仍不是完整通用路线规划；未动态化的候选族需要明确不可用说明，不得用旧模板补造。 |
| 成都春熙路 -> 深圳福田中心区 | 可解析城市、生成成都东/深圳北和机场候选，并返回路线覆盖不足说明。 | 当前不生成门到门方案，避免把未实现城市对伪装成样例路线。 |
| 本地接驳段 | 覆盖 TAXI、SUBWAY、BUS、WALK 选项、可用性判断、接驳说明和重算。 | 完整逐站公交/地铁路线、打车平台实时派单和生产级导航仍依赖授权 Provider。 |
| 航班段 | 可在测试 fixture 下覆盖直飞、中转、多机场组合、自采 Provider 解析、舱位筛选、证据快照和阻断语义。 | 未启用审批通过的官方公开航司采集源时不得承诺真实报价、可售状态或舱位；缺价、无可售信号、源站不可用或结构漂移时不得生成对应航班方案。 |
| 铁路段 | 可在测试 fixture 下覆盖 12306 查询解析、车次、座席、动态中转站、多段中转、票源增强和阻断语义。 | 不承诺余票数量、可售交易结果、补票成功或购票成功；缺价、无票、限流和站点码缺失必须阻断对应铁路方案。 |
| Redirect-only | 覆盖 12306、航司官网、高德地图跳转和 fallback instruction。 | 只跳转，不登录、不抢票、不下单、不支付、不保存第三方凭证。 |

当前可以对外演示的是“可解释的规划骨架 + 地点/节点候选 + 12306 公开铁路查询 + 真实公开只读 Provider smoke + 授权缺失时的透明降级/阻断”。不能对外演示或承诺“任意城市实时最优路线、余票数量、可售交易结果、自动购票、抢票、支付、第三方账号登录、LLM 生成交通事实”。

## 更新规则

- 新增或删除 `DataSourceConfig.source_id` 时，必须更新 Provider 能力矩阵。
- 新增 Planner 方案类型、路线覆盖城市、交通模式或降级路径时，必须更新产品能力矩阵和 Planner 覆盖表。
- 新增测试 fixture、fake client 或 preview 数据时，必须在自动化 Fixture 边界表中说明用途和运行时禁止范围。
- 能力状态从“进行中”变为“验收通过”时，必须补充对应测试、CI、smoke 或 App 验收证据。
