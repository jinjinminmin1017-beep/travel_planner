# Architecture

更新日期：2026-08-14

## 文档定位

本文只描述两类内容：

- **当前架构**：已经在代码、配置和接口中生效的系统结构。
- **已批准目标架构**：尚未实现，但已经确定边界并拆成开发、测试任务的下一阶段变更。

本文不是变更日志。已经完成、被替代或退出运行路径的历史方案不继续保留；历史原因通过 Git、`docs/Dev/`、`docs/Test/` 和专项证据文档查询。新增架构必须合并进对应主题，禁止继续按日期在文件末尾追加同类章节。

## 1. 系统目标与架构不变量

本项目是 Expo/React Native 客户端与 FastAPI 后端组成的行程规划应用。系统负责解析自然语言需求，组合门到门交通方案，计算费用、时间、舒适度和风险，最后给出可解释推荐。

必须保持以下不变量：

- 只有具备可追溯来源的真实交通事实才能形成可用计划；缺失核心事实时 fail-closed，不生成模拟班次、模拟车次或虚构价格。
- 票务时刻、精确价格、席别/舱位、库存语义和交易跳转必须来自活动票务 Provider；内部计算只能派生总价、接驳、时间和评分。
- 活动异步任务中的 `plans=[]` 表示“仍在规划”，不是“没有方案”；只有服务端终态才能驱动结果页、无匹配页或失败页。
- 前后端合同以 `backend/app/models/schemas.py` 为源，经 `schemas/*.schema.json` 导出，并由 `frontend/src/types/index.ts` 消费；禁止三处独立演化。
- 数据源启用状态、许可证状态、QPS、超时、Host allowlist 和 Secret 均从 ENV 类型化加载；运行时不读取第二套 JSON 配置。
- 金额使用最小货币单位整数，时间点必须带时区；国内规划统一按 Asia/Shanghai 解释服务日期。

## 2. 运行拓扑

```text
Expo / React Native App
  -> FastAPI HTTP API
       -> request validation / security middleware
       -> intent parsing and location resolution
       -> transport-node selection
       -> planner orchestration
            -> map/geocode/weather providers
            -> Fliggy FlyAI ticket provider
            -> deterministic transfer/cost/risk engines
            -> constraint filtering and recommendation
       -> progressive job snapshots
       -> SQLite persistence + in-process TTL cache
  <- polling snapshots / verified plans / typed failures
```

主要进程：

- 前端入口：`frontend/index.ts` -> `frontend/src/App.tsx`。
- 后端入口：`backend/app/main.py` 中的 FastAPI `app`。
- 当前部署是单后端进程、本地 SQLite 和进程内缓存；Redis、PostgreSQL、分布式任务队列尚未实现。
- FlyAI 通过仓库固定版本的官方 CLI 子进程调用；运行时禁止 `npx -y` 动态安装。

## 3. 前端架构（当前）

### 3.1 页面与状态

- `frontend/src/App.tsx` 是当前应用壳、主流程与运行时状态聚合入口。
- `frontend/src/components/input/TravelInputScreen.tsx` 负责自然语言输入、快捷偏好与本地历史。
- `frontend/src/components/results/` 负责正常结果、路线分段、费用、交通方式入口和推荐说明。
- `frontend/src/components/constraints/` 负责约束无匹配与最近备选，不与普通空态混用。
- 当前未引入 React Navigation、Redux 或 Zustand；页面切换和主要状态仍集中在 `App.tsx`。

### 3.2 异步规划状态机

`frontend/src/planning/planningState.ts` 统一解释规划状态：

- `PENDING/RUNNING`：任务活动中，可有零个或多个已安全发布计划。
- `COMPLETE/PARTIAL`：规划终态；`PARTIAL` 表示部分来源或交通方式不可用，不表示返回事实可疑。
- `NO_MATCH`：真实候选经过约束计算后无可推荐计划，进入独立无匹配页面。
- `FAILED`：没有形成可验证核心方案且任务已失败。

客户端轮询耗尽、App 进入后台或单次 GET 失败只会暂停观察。客户端必须保留 `job_id`、`polling_url` 和最后快照，恢复时继续查询同一任务，不创建重复 job。

### 3.3 前端边界

- 前端只展示后端给出的计划、来源状态和推荐结论，不自行拼装铁路/航班事实。
- 重算成功后以完整结果集快照替换本地结果；失败时保留旧快照。
- 预订请求只提交 `plan_id`、`segment_id` 和 redirect type，不接收或保存第三方原始 URL。

## 4. API 与合同架构（当前）

完整合同以 `docs/API_CONTRACT.md` 为准。主要流程接口为：

- `POST /api/travel/parse`：仅解析自然语言输入。
- `POST /api/travel/plan`：同步规划入口，主要用于兼容和测试。
- `POST /api/travel/plan/async`：客户端主规划入口。
- `GET /api/travel/jobs/{job_id}`：获取渐进快照或终态。
- `POST /api/travel/jobs/{job_id}/retry|cancel`：重试或取消。
- `POST /api/travel/recalculate`：席别、舱位、接驳等重算。
- `POST /api/redirect/booking`：服务端校验并返回预订跳转。
- `GET /api/data-sources/status`：数据源配置和真实运行健康状态。

合同规则：

- API schema version 当前为 `1.18`。
- 统一错误结构由 `ErrorResponse` 表达，包含稳定错误码、用户信息、重试语义和 request id。
- `application_scope=RESULT_SET` 的铁路席别调整按同一车次传播，但不改变其他车次或全局请求偏好。
- `redirect_type=FLIGGY` 的 URL 只允许从已持久化且与 plan/segment 绑定的 booking reference 中读取。

## 5. 后端分层与模块职责（当前）

### 5.1 接口层

`backend/app/main.py` 负责：

- FastAPI 路由、请求校验、安全 middleware 和统一异常转换。
- 异步任务创建、渐进快照写入、轮询、取消和重试。
- 规划 deadline 创建与执行指标上报。

接口层不应实现 Provider 解析、候选组合或推荐算法。

### 5.2 业务编排层

- `services/intent_parser.py`：将自然语言转换为 `TravelRequest`。
- `services/location_resolver.py`：地点解析与交通节点关联。
- `services/planner.py`：铁路、航班、混合交通和接驳的总编排入口。
- `services/local_transfer_engine.py`：规划请求内复用地点解析和地图路线。
- `services/rail_connection_matcher.py`：对两段完整铁路 offer 做确定性连接匹配。
- `services/offer_preselection.py`：在完整铁路 offer 上按约束分桶和稳定预排序。
- `services/candidate_generator.py`、`plan_variant_materializer.py`：形成有界候选与方案变体。
- `services/constraints/`：约束计算、安全门禁、Pareto 筛选和最近备选。
- `services/recommendation.py`：只在安全候选集上生成推荐结果。
- `services/result_set_preferences.py`：将车次级席别选择传播到结果集中匹配计划。

### 5.3 基础设施层

- `data_sources/config_loader.py`：从 ENV 构造不可变、类型化配置快照。
- `data_sources/provider_registry.py`：adapter settings 与 Provider factory 注册。
- `data_sources/rate_limiter.py`：在真实 HTTP/CLI 请求边界执行 source 级 QPS。
- `data_sources/runtime_health.py`：记录成功、失败、连续失败和 CLOSED/OPEN/HALF_OPEN 熔断状态。
- `services/persistence.py`：SQLite 持久化。
- `services/cache_store.py`：进程内 TTL 缓存。
- `services/observability.py`：规划阶段、deadline 和结果指标。

### 5.4 自然语言相对日期与时间解析（已批准目标，待实现）

当前问题：

- `intent_parser.py` 的确定性日期规则只覆盖今天、明天、后天、明确年月日和有限月日格式；“本周几、下周几、最近的周几、这个周末、月底、N 小时后”等常见表达没有完整覆盖。
- LLM 首次输出和一次 repair 都可能返回不符合 `TravelRequest.travel_date` 的值；确定性兜底也无法识别时，接口会把有日期语义的输入误报为缺少日期。
- 当前只把 `current_date` 传给 LLM，没有传带时区的权威 `current_datetime`；因此不能可靠处理跨午夜的“N 小时后”。

目标方案：

- 后端使用 `Asia/Shanghai` 的带时区当前时刻作为国内行程解析的唯一权威基准，不依赖客户端时钟，也不依赖服务器默认时区。
- 采用“LLM 识别语义、后端确定性归一化和校验”的边界：LLM 不直接决定最终日期；后端将相对表达转换为规范 `travel_date` 和 `TimePoint`。
- 明确支持今天、明天、后天、本周几/这周几、下周几/下星期几、最近的周几及“N 小时后”；跨午夜时同步更新 `travel_date`。
- `travel_date` 输出必须规范化为 `YYYY-MM-DD`；所有具体时间输出为包含 `datetime`、`timezone`、`source_timezone` 的 `TimePoint`。
- “这个周末”“月底”等不能唯一落到单个出发日的表达不得静默猜测；返回 `PARSE_NEEDS_INPUT` 和针对性 follow-up question，引导用户选择具体日期。
- 已明确但 LLM 格式错误的日期应由后端从原始输入恢复；只有信息确实缺失或存在无法消除的歧义时才追问。

数据流：

```text
raw_user_input
  -> 生成 Asia/Shanghai current_datetime
  -> LLM 提取日期/时间语义
  -> 后端相对日期时间解析器确定性归一化
  -> Pydantic TravelRequest 校验
  -> 成功进入规划，或返回具体字段与问题的 PARSE_NEEDS_INPUT
```

影响范围：

- 后端：`services/intent_parser.py`、`data_sources/llm_providers.py`、Intent/repair prompts 和 API 错误映射。
- 前端：继续消费既有 `PARSE_NEEDS_INPUT.details.follow_up_questions`；若当前只显示通用错误，需要展示服务端具体追问。
- API Schema 与数据库：不新增字段、不升级 schema version、不需要数据库迁移。
- 测试：固定时钟和 Asia/Shanghai 时区，覆盖周边界、月/年边界、跨午夜、过去日期和歧义追问。

风险与回滚：

- 风险：周定义、周末范围和口语省略可能导致静默误解；使用显式词典、确定性算法和追问避免猜测。
- 风险：测试依赖真实系统时间会产生不稳定结果；必须注入固定 `current_datetime`。
- 回滚：保留现有明确日期与今天/明天/后天规则；新解析器可通过独立功能开关关闭，回滚不改变 `TravelRequest` 合同。

## 6. 规划数据流（当前）

```text
raw input / structured request
  -> Pydantic validation
  -> intent parser
  -> location resolver
  -> station / airport candidate selection
  -> determine in-scope transport modes
  -> query enabled factual providers
  -> materialize complete door-to-door plans
  -> apply hard safety gates
  -> constraint classification and Pareto selection
  -> deterministic ranking + optional LLM explanation
  -> publish progressive snapshots
  -> persist final response and plan bindings
```

关键规则：

- 接驳必须参与门到门总时间和总费用，不能只比较城际段。
- Provider 返回的 origin/destination、时刻、价格和产品身份必须保持关联，不能跨 item 拼接。
- 约束分为硬约束、软偏好和安全门禁；违反安全门禁的计划不能进入推荐和最近备选。
- 最近备选必须说明差距和失败原因，不能把安全不合格方案包装为“差一点”。
- progressive snapshot 只能发布已经完整且通过安全门禁的计划。

## 7. 数据源架构（当前）

### 7.1 配置与注册

- `.env.example` 是非敏感变量的唯一清单，本地 Secret 位于根目录 `.env`。
- `TRAVEL_DATA_SOURCE_IDS` 声明允许加载的 source id；每个 source 使用 `TRAVEL_SOURCE_<ID>_*` 配置。
- 未在代码 `SOURCE_DEFINITIONS` 和 adapter registry 中注册的 source 无法通过 ENV 启用。
- 启用的外部源必须配置正 QPS、超时和必要 Host allowlist；Secret 不进入日志、响应、SQLite 或命令行参数。

### 7.2 票务事实源

`fliggy_flyai` 是当前航班和铁路唯一可配置票务事实源：

- `flyai_cli_client.py` 负责无 shell 子进程、超时、退出码、stdout JSON 和 stderr 门禁。
- `fliggy_flyai_provider.py` 负责航班/铁路结构校验、精确价格、60 秒缓存、single-flight、item fingerprint 和 `jumpUrl` allowlist。
- `flight_providers.py`、`rail_providers.py` 负责搜索请求、结果聚合和统一失败语义。
- `provider_booking.py` 只在规划阶段生成 plan/segment-bound 的 `FLIGGY` booking reference。
- 没有 FlyAI 验证时，不生成铁路/航班路线卡、价格、席别/舱位、余票或交易链接。

### 7.3 地图、地理编码和辅助来源

- 路线：OSRM 当前可作为公开只读路线源；高德/百度路线由许可证和配置门禁控制。
- 地理编码：Nominatim 当前可用；高德 geocode/place search 由配置门禁控制。
- 天气：Open-Meteo 提供预报事实。
- OpenSky 只提供飞行状态类辅助信息，不提供票务和价格。
- `real_llm` 默认关闭，只能生成解释，不能新增或修复交通事实。

### 7.4 失败语义

至少区分：

- `VERIFIED`：存在通过校验的真实结果。
- `EMPTY`：来源成功返回确定性空结果。
- `RATE_LIMITED`、`TIMEOUT`：暂时性外部故障，可按有界策略重试。
- `INVALID_RESPONSE`、`PRICE_NOT_EXACT`：响应不满足事实门禁，不可发布。
- `DISABLED`、`PROVIDER_UNAVAILABLE`：来源未启用、未认证或熔断。

启用配置不等于健康。`/api/data-sources/status` 的运行状态来自真实调用事件；`/api/health` 仅表示 FastAPI 存活。

## 8. 持久化、缓存与幂等（当前）

SQLite 当前包含：

- `travel_responses`：完整规划响应快照。
- `travel_plans`：可按 plan id 读取的计划与预订绑定。
- `feedback`：用户反馈记录。

边界：

- 运行时 job store 与 TTL cache 位于进程内，进程重启后不保证保留活动任务和缓存。
- 外部查询缓存必须包含影响事实的完整查询维度；不能用城市级缓存复用不同日期或站点的票务结果。
- 重算和 redirect 必须基于已持久化计划校验归属，禁止客户端提供权威价格或跳转地址。
- 当前单实例 SQLite 架构不支持多实例一致性；扩展到多实例前必须单独设计共享任务、缓存和数据库迁移。

## 9. 铁路规划架构（当前）

### 9.1 当前流程

```text
地点解析
  -> 从本地交通节点目录选择出发/到达站候选
  -> 对站点对调用 FlyAI 发现直达铁路 offer
  -> 对候选换乘站调用两段 FlyAI 查询
  -> rail_connection_matcher 验证站点身份和换乘窗口
  -> offer_preselection 按约束筛选完整 offer
  -> 构建门到门铁路或空铁混合计划
```

当前实现的正确边界：

- 同一列车必须满足上车站序在下车站序之前。
- 两段换乘必须满足站点身份、第一段到达、第二段发车和动态安全窗口。
- FlyAI `RailOffer.stop_sequence` 当前只覆盖查询的起终点，不能作为全国完整经停图。
- `hub_rank` 是交通节点目录中的枢纽排序特征，不代表用户地点相关性，也不代表列车覆盖能力。

### 9.2 当前性能与正确性问题

- 直达路线需要枚举多个出发站/到达站组合；换乘会进一步乘以候选枢纽数。
- FlyAI 当前 QPS 为 1、单次超时为 30 秒，外部调用数量直接决定规划延迟。
- 当前站点选择先按城市和 `hub_rank` 截断，可能覆盖明确地点语义。例如输入“宜兴”时，宜兴站可能被无锡站、无锡东站挤出候选。
- FlyAI 适合验证实时票务事实，不适合承担全国路由图的重复发现计算。

上述问题由下一节批准的目标架构解决；在目标实现启用前，当前实时查询路径继续作为生产路径。

## 10. 本地铁路时刻表快照与实时核票架构（已批准目标，待实现）

### 10.1 目标与非目标

目标：

- 在本地 SQLite 建立全国 G/D/C 铁路时刻表数据库，首次补全从当天 D0 到 D+14 的 15 个服务日，并在之后每天滚动更新。
- 本地计算直达和一次换乘候选，把 FlyAI 调用收敛为少量实时核票。
- 明确站点语义优先于静态枢纽等级，修复宜兴站被截断问题。
- 导入过程低频、单线程、幂等、可断点续跑，并能安全保留上一有效快照。

非目标：

- 本地库不保存余票、实时价格、席别库存、预售状态或预订链接。
- 第一期不支持任意多次换乘，不在内存中构建全国无界图。
- 不绕过验证码、HTTP 429、登录挑战或其他访问控制。
- 不使用日期停留在 2022 年的公共 `train_list.js` 推导当前运行图。

### 10.2 目标数据流

```text
首次建库（bootstrap）
station_name.js -> 站点 telecode
  -> 按 D0～D+14 逐日发现列车
  -> 去重 train_no_internal
  -> 逐车查询完整停站
  -> 校验 G/D/C、站序、跨日时间与日期完整性
  -> 为每个服务日写入并激活完整批次

每日滚动刷新（refresh）
  -> 移出已经过期的日期
  -> 完整导入新的 D+14
  -> 重新发现 D0～D+13 的车次清单
  -> 复用未变化车次，重查新增或发生变化的完整停站
  -> 完整性校验通过后按服务日原子切换 ACTIVE 批次
  -> 失败日期保留上一 ACTIVE 批次并等待补跑

在线规划
地点解析 -> 强匹配站点优先
  -> 本地查询直达 + 一次换乘
  -> 有界排序并生成 Top 候选
  -> 按 (service_date, origin_station, destination_station) 分组
  -> FlyAI 一次查询验证同组多个候选车次
  -> 有票则发布；无票则进入下一候选组
  -> 达到查询预算或来源不可用时结束
```

### 10.3 数据生命周期：首次建库与每日滚动更新

首次建库：

- 本地数据库使用现有 SQLite 基础设施，首次运行建立 D0～D+14 共 15 个服务日的数据窗口。
- 日期按近到远处理，使近期规划尽早可用；但只有某个服务日完成车次发现、所有唯一 G/D/C 详情获取和完整性校验后，该日期才可标记为 ACTIVE。
- “已补充完整”是逐服务日状态，不是只看数据库有记录：发现任务必须全部完成、详情不得缺失、站序和跨日时间必须合法、服务数异常必须低于门禁。
- 首次任务中断后从 checkpoint 继续，不清空已经完成的 ACTIVE 日期。

每日滚动更新：

- 每天由操作系统调度任务调用 refresh 脚本一次，不在 FastAPI 进程或用户规划请求中触发；运行时间通过部署配置设置为本地低峰时段，不把具体钟点硬编码进业务代码。
- 窗口始终定义为执行日 D0～D+14。过期日期退出规划窗口，新出现的 D+14 必须执行完整导入。
- D0～D+13 重新执行车次发现并与当前 ACTIVE 批次比较；未变化车次可复用其完整停站，新增、取消或摘要指纹变化的车次必须重新查询详情。
- 差异刷新仍以“新批次完整”为激活条件，不能只追加新车而遗漏已经取消的车次。只有发现遍历完整结束后，才允许从新批次删除旧车次。
- 调度停机或某日刷新失败时，下次定时或手工 refresh 执行 catch-up：先补齐缺失的 D+14，再按日期新鲜度更新窗口内旧批次。
- 每个服务日保留当前 ACTIVE 和至少一个上一成功批次用于回滚；过期日期及更老 RETIRED 批次按可配置保留期清理。
- 若目标日期没有 ACTIVE 批次或批次超过新鲜度门禁，Planner 不使用该日期的本地数据，而是回到当前实时路线发现路径。

### 10.4 导入边界

- 先用小日期、小站点范围 POC 验证当前可用的车次发现和完整停站响应，再允许全国遍历。
- 单线程执行，默认请求间隔 1～2 秒；只对连接中断、超时等暂时错误有限退避。
- 验证码、429 或明确访问限制出现时暂停并保存 checkpoint，不自动绕过。
- 每个发现任务和车次详情任务完成后写 checkpoint；resume 跳过已经完成的稳定任务键。
- 记录日期、任务键、解析版本、响应哈希、统计和脱敏错误，不记录 Cookie、验证码内容或 Secret。
- 每个服务日先写 STAGING 批次；只有服务数、停站数、时间合法性和异常率通过后才原子替换该日期的 ACTIVE 批次。

### 10.5 数据模型与用途

```text
rail_timetable_batch
- batch_id                    PK
- service_date                本批次对应的服务日期
- status                      STAGING | ACTIVE | FAILED | RETIRED
- source_version              来源/解析器版本
- started_at                  带时区
- completed_at                带时区，可空
- service_count
- stop_count
- error_count

rail_service
- service_id                  PK
- batch_id                    FK -> rail_timetable_batch.batch_id
- service_date                服务日期（Asia/Shanghai）
- train_no_internal           12306 内部车次标识
- train_number                展示车次号，如 G123
- origin_station_code         始发站 telecode
- destination_station_code    终到站 telecode
- fetched_at                  带时区

rail_stop_time
- service_id                  FK -> rail_service.service_id
- stop_sequence               从 1 开始的停站序号
- station_code                站点 telecode
- arrival_time                当地钟表时间，始发站可空
- arrival_day_offset          相对 service_date 的天数偏移
- departure_time              当地钟表时间，终到站可空
- departure_day_offset        相对 service_date 的天数偏移
```

用途：

- `rail_timetable_batch` 管理每个服务日的 staging、激活和回滚，避免失败导入覆盖可用数据。
- `rail_service` 表示某一服务日实际运行的一趟列车，是路线搜索的服务主体。
- `rail_stop_time` 表示该列车完整站序和跨日到发时间，用于判断乘车方向、区间时长和换乘可行性。
- 站名仍由现有交通节点目录解析；铁路关联使用稳定 `station_code`，不依赖展示名称。
- 车站坐标属于无服务日期维度的站点主数据；`rail_service` 和 `rail_stop_time` 只通过 `station_code` 引用交通节点，不得按 `service_date` 复制经纬度。

约束与索引：

- `rail_timetable_batch` 同一 `service_date` 同时只能有一个 ACTIVE 批次，该约束在切换事务中保证。
- `rail_service` 唯一约束为 `(batch_id, train_no_internal)`。
- `rail_stop_time` 唯一约束为 `(service_id, stop_sequence)`。
- 至少建立 `(batch_id, service_date, train_number)`、`(service_id, stop_sequence)` 和用于按活动日期、站点、发车时间查询的索引。
- 到达和发车分别保存 day offset，禁止仅比较 `HH:mm` 字符串处理跨午夜。

该目标需要数据库迁移，只新增铁路快照表和索引，不改写已有计划、响应和反馈表。

### 10.6 本地路线搜索

#### 铁路站点地理目录与候选排序（已批准目标，待实现）

当前交通节点目录不能支持可靠的“附近车站”规划：3397 条铁路站点记录中只有 15 条内部 seed 带坐标，3382 条 `rail_12306_station_catalog` 记录均无坐标。12306 `station_name.js` 提供站名、电报码、拼音和城市身份，不提供经纬度；坐标必须由独立、许可证允许的地理数据源补充，不能把缺失坐标解释为零距离或用 `hub_rank` 代替地点相关性。

目标数据边界：

- `station_code` 是铁路站点实体的稳定主键；内部 seed、12306 目录和坐标来源必须合并到同一实体，禁止因 seed 缺少电报码而同时保留两条“上海虹桥”参与规划。
- 坐标存储和补全去重键只使用 `station_code`，不包含 `service_date`、车次或查询日期。同一车站跨 D0～D+14 及历史服务日共享一条坐标主记录，时刻表每日刷新不得重复计算、请求或落库经纬度。
- 每条铁路站点保留站名来源和坐标来源的独立元数据，至少包含 `coordinate_source_id`、`coordinate_source_version`、`coordinate_updated_at`、`coordinate_quality` 和坐标解析状态；不得用站名目录的来源冒充坐标来源。
- 全量目录中的每个12306站点都必须有明确的坐标解析状态。只有坐标通过格式、范围、城市归属、站名/别名和重复实体校验的客运站才能标记为 `planning_enabled`。
- 所有 `planning_enabled` 铁路客运站坐标覆盖率必须为 100%；未解析或存在歧义的站点继续保留在原始目录和质量报告中，但不得进入距离排序、地图接驳或“最近车站”结论。
- 坐标补全是离线、可断点续跑、可审计的数据构建任务，不在用户规划请求中批量地理编码；导入遵守来源 QPS、许可证、缓存和访问控制，不绕过限制。
- 已存在 `VERIFIED` 坐标且坐标来源版本未变化时，补全任务必须直接复用；只有来源版本更新、站点迁址/更名或显式强制复核时才重新解析。该规则不影响可能随出行时刻变化的道路路线与交通耗时计算。
- 新目录先写 staging 文件并生成覆盖率、歧义、重复、越界和变更距离报告；全部门禁通过后原子激活，失败时继续使用上一版本。

候选站和站点对排序规则：

1. 用户明确说出完整站名时，只允许规范站名或已登记别名做确定性精确匹配；普通地址/POI 不得因前缀子串产生强站点匹配，例如“上海南翔格林公馆”不得匹配“上海南站”。
2. 对普通地址/POI，先按已验证坐标做有界直线距离预筛，再通过地图 Provider 计算首程/末程真实道路时间和费用；缺坐标候选直接排除并记录诊断。
3. 本地运行图负责判断候选站之间是否有满足日期、方向和时间窗的可达车次；物理距离最近但无可用车次的站点不能直接胜出。
4. Planner 在有界预算内比较多个出发站与到达站组合的完整门到门时间、费用、换乘和风险；不得因第一个站点对先返回 `max_plans` 条车次而提前结束全局比较。
5. `hub_rank` 只允许作为距离、接驳、可达性和用户约束均近似相同时的最终弱 tie-breaker，不能补偿坐标缺失，也不能覆盖门到门成本。

目标数据流：

```text
12306 station_code/站名目录
  + 许可证允许的铁路站点坐标来源
  -> 按 station_code 合并、坐标校验、重复实体消解
  -> staging 质量报告与 100% planning_enabled 坐标门禁
  -> 原子激活 transport_nodes 目录

用户地址/POI -> 地理编码
  -> 附近 planning_enabled 站点预筛
  -> 地图接驳时间/费用
  -> 本地运行图可达性
  -> 多站点对有界核票
  -> 完整门到门全局比较
```

- 直达：同一 ACTIVE `service_id` 同时包含出发站和到达站，且出发 `stop_sequence <` 到达 `stop_sequence`。
- 一次换乘：第一段到达的绝对时间加安全换乘窗口，不晚于第二段发车的绝对时间。
- 支持有界跨日；限制服务日期、换乘站数、等待时间、总时长和候选数量。
- 查询必须依赖数据库索引，不得把 15 天全部停站加载到 Python 后构建全国图。
- 排序综合直达优先、总耗时、换乘等待、时间偏好、站点相关性和去车站成本。

站点候选规则：

1. 用户明确指定站名时，精确站点必须保留。
2. 区县/地点强匹配站点先占候选名额。
3. 剩余名额再分配给城市内其他车站和扩展枢纽。
4. `hub_rank` 只能用于同相关性层级内的弱排序，不能覆盖强匹配。

因此输入“宜兴”或“宜兴站”时，宜兴站必须进入首批候选；无锡站、无锡东站只能作为扩展候选。

### 10.7 FlyAI 实时核票

- 本地查询结果的初始内部状态为 `SCHEDULE_CANDIDATE`，只表示运行图中存在。
- 候选按 `(service_date, origin_station, destination_station)` 分组；一次 FlyAI 查询匹配同组多个候选车次。
- 使用服务日期、车次号、起终站和时间窗口做确定性关联；无法唯一关联时 fail-closed。
- 完整价格、席别/库存语义和 allowlisted `jumpUrl` 均存在时，候选转为 `AVAILABLE` 并可发布。
- 内部失败状态至少区分 `SOLD_OUT`、`NOT_ON_SALE` 和 `PROVIDER_UNAVAILABLE`。
- 无票进入下一候选组；每个 job 设置分组数、总时长和重试预算，禁止无限重查。
- 只有超时和限流允许有限退避；确定性空结果、无票、结构错误和进程崩溃不在同一候选上循环重试。

MVP 只向现有 API 发布 FlyAI 已验证方案，因此 `docs/API_CONTRACT.md` 和 schema version 暂不修改。未来若展示“参考车次/暂未核票”，必须先定义新的 API 状态和前端交互。

### 10.8 模块与配置变更

建议新增：

- `backend/app/data_sources/rail_12306_timetable_provider.py`：低频时刻表导入适配器，不注册为在线票务事实源。
- `backend/app/services/rail_timetable_store.py`：批次、幂等写入、激活和索引查询。
- `backend/app/services/rail_route_search.py`：直达与一次换乘候选搜索。
- `backend/app/services/rail_inventory_verifier.py`：FlyAI 分组、预算、匹配和状态转换。
- `scripts/import_12306_timetable.py`：日期范围、间隔、checkpoint、resume 和 dry-run。
- `scripts/install_rail_timetable_refresh.ps1`：在 Windows Task Scheduler 注册、检查和卸载每日 refresh 任务；其他部署环境使用等价 cron/systemd timer。
- `scripts/enrich_rail_station_coordinates.py`：按 station code 补全、校验和报告铁路站点坐标，支持 dry-run、checkpoint、resume 和 staging 激活。
- SQLite migration：新增三张铁路快照表及索引。

建议新增配置：

- `TRAVEL_RAIL_TIMETABLE_SNAPSHOT_ENABLED=false`
- `TRAVEL_RAIL_LOCAL_ROUTING_ENABLED=false`
- `TRAVEL_RAIL_TIMETABLE_REFRESH_ENABLED=false`
- `TRAVEL_RAIL_TIMETABLE_HORIZON_DAYS=15`
- `TRAVEL_RAIL_TIMETABLE_REFRESH_AT=<local HH:mm>`
- `TRAVEL_RAIL_TIMETABLE_RETENTION_DAYS=<positive integer>`

Planner 只有在两个开关开启、目标日期存在有效 ACTIVE 批次时才使用本地候选。快照不可用时回到当前实时路线发现路径；“快照不可用”和“本地确认无车”必须是不同内部结果。

### 10.9 性能、验收与回滚

性能门禁：

- 本地直达搜索 P95 <= 100ms。
- 本地一次换乘搜索 P95 <= 500ms。
- 典型铁路规划 FlyAI 查询 <= 3 个站点组。
- 记录 cold/warm P50/P95/P99、本地候选数、核票组数、缓存命中和预算耗尽原因。

正确性门禁：

- 重复导入和 resume 不生成重复服务或停站。
- 失败 STAGING 批次不影响上一 ACTIVE 批次。
- bootstrap 完成后 D0～D+14 均有通过完整性门禁的 ACTIVE 批次；每日 refresh 后窗口向前滚动一天。
- 每日刷新能识别新增、取消和摘要变化车次；任务中断后 catch-up 不产生缺口或重复数据。
- 宜兴强匹配、方向、跨午夜、换乘安全窗口和无票换下一候选均有回归测试。
- 所有 `planning_enabled` 铁路客运站坐标覆盖率为 100%，且每条坐标具有独立来源、版本、更新时间和质量状态；未知或歧义坐标不会进入候选排序。
- “上海南翔格林公馆”不得因子串命中上海南站；南翔北、上海虹桥等附近且可达站点必须按真实接驳和运行图事实参加比较。
- 出发端和到达端均完成多个站点组合的有界门到门比较；第一组票务结果达到展示数量不得触发提前返回。
- 没有 FlyAI 验证的本地候选永远不形成可预订路线卡。

主要风险：

- 12306 响应结构变化：版本化 parser 和 fixture；结构漂移时停止激活新批次。
- 全国遍历耗时或触发限制：单线程、低频、checkpoint、有限重试和人工暂停。
- 运行图临时调整：本地只生成候选，最终仍由 FlyAI 实时验证。
- 换乘组合爆炸：限定一次换乘、时间窗口、候选上限和核票预算。
- 坐标来源许可或覆盖不足：只接入已批准来源，未通过校验的站点保持禁用并输出质量报告，不猜测坐标。
- 同名站、迁址站或重复 seed 错误合并：以 station code 为主键，名称只用于校验，坐标大幅变化必须人工复核。

回滚：坐标目录激活前保留上一版本，异常时原子恢复旧目录；关闭 `TRAVEL_RAIL_LOCAL_ROUTING_ENABLED` 可恢复当前实时路线发现，必要时关闭快照导入。新增表和质量报告保留，不删除历史计划，不放宽实时票务门禁。

对应任务：

- `docs/Dev/task_from_arc_for_dev_20260804_rail_timetable.md`
- `docs/Dev/task_from_arc_for_dev_20260814_rail_station_geodata.md`
- `docs/Test/task_from_arc_for_test_20260804_rail_timetable.md`
- `docs/Test/task_from_arc_for_test_20260814_rail_station_geodata.md`

## 11. 安全与可观测性（当前）

### 11.1 安全边界

- API Key、Cookie、token 和第三方原始敏感响应不得进入日志、API、SQLite、测试快照或 Git diff。
- 外部 URL 必须经过 HTTPS 和 Host allowlist 校验；客户端不能提交权威跳转 URL。
- Provider 子进程不使用 shell，Secret 通过受控环境传入，不出现在进程命令行。
- 所有用户输入经过 Pydantic 与业务校验；错误响应不暴露内部堆栈或 Secret。

### 11.2 可观测性

- 每个请求携带 request id、trace id 和 correlation id。
- 规划指标覆盖阶段耗时、渐进快照、deadline outcome、候选与最终计划数量。
- Provider 指标区分成功、空结果、超时、限流、结构错误、精确价格失败和熔断。
- FlyAI readiness、真实 exit 0、空 stderr 和结构校验是启用真实票务模式的门禁；fixture 通过不能替代真实环境认证。

## 12. 启动、测试与发布门禁

启动方式：

- 后端：`python -m uvicorn app.main:app --reload --app-dir backend`
- 前端：`cd frontend && npm run start`
- 真机调试：`scripts/device-debug.ps1`；无可用 FlyAI 时必须显式选择无票务调试模式。

每次架构实现至少通过：

- 后端 pytest。
- 前端 TypeScript typecheck 与 Expo export。
- JSON Schema 导出与 diff 检查。
- Provider 配置检查和脱敏 fixture 测试。
- 涉及真实来源时的显式低频 smoke；未执行必须标记为未验证，不能以 fixture 代替。

发布原则：

- 新数据源、数据库路径或 Planner 分支默认由功能开关关闭。
- 先通过 migration、fixture、集成测试和 benchmark，再灰度开启。
- 回滚优先关闭功能开关；除非有独立迁移方案，不在回滚时删除新表或改写历史计划。
