# ARC-20260802-01 飞猪 FlyAI 唯一票务事实源开发任务

来源：用户已取得正式 FlyAI API Key，并要求弃用航司查询，只接入飞猪展示航班/高铁路线卡并跳转飞猪交易。

状态：代码开发完成，在线验收阻塞（2026-08-02）。

执行说明：固定版本 CLI、航班/铁路解析、精确价格门禁、60 秒缓存与 single-flight、V1.18 合同、plan-bound `FLIGGY` redirect、前端 CTA、旧票务源运行退役和自动化回归均已实现。当前仓库根目录 `.env` 未检测到非空 `TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY`，且无 Key 的 Windows 探测中官方 CLI 在输出体验模式 JSON 后以 libuv assertion 非零退出；因此正式 Key smoke、目标环境 exit 0 与 50 样例 cold/warm 性能门禁尚未执行，本任务不得标记“验收通过”。

## 1. 目标与边界

- 新增一个 `fliggy_flyai` Provider，同时为现有航班和铁路规划管道提供结构化 offer。
- App 内继续展示原生路线卡；支付、实名、下单全部跳转飞猪，后端不保存飞猪账号、乘客或支付信息。
- FlyAI 上线时从默认运行清单移除航司、航司浏览器和 12306 查询，不实现运行时 fallback。
- 只使用官方 `@fly-ai/flyai-cli`/MCP能力，不调用未公开内部 HTTP，不逆向签名或私有协议。
- 外部合同升级为 `1.18`，仅新增 OTA 数据源类型和 `FLIGGY` redirect type；规划请求结构保持不变。

## 2. Secret 与配置

### 2.1 用户本地配置位置

真实 Key 由用户写入仓库根目录 `.env`：

```dotenv
TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY=<正式 Key>
```

不得读取前端环境变量，不得将真实值复制到 `.env.example`、测试或文档。

### 2.2 配置模型

- 在 `SOURCE_DEFINITIONS` 注册 `fliggy_flyai`，`source_type=OTA`。
- 新增 CLI source settings，至少支持：`API_KEY`、`EXECUTABLE`、`TIMEOUT_SECONDS`、`CACHE_TTL_SECONDS`、`QPS_LIMIT`。
- `.env.example` 增加空 Key 与保守非敏感默认值。
- `TRAVEL_DATA_SOURCE_IDS` 加入 `fliggy_flyai`，在切换提交中移除：
  - `airline_9c_public_query`
  - `airline_hu_public_query`
  - `airline_qw_public_query`
  - `airline_mu_browser_query`
  - `rail_12306_public_query`
  - `airline_official_redirect`
  - `rail_12306_redirect`
- `COMMERCIAL_ALLOWED` 默认保持 `false`；没有书面商业许可不得改为 `true`。

## 3. 官方 CLI Client

- 新增 `flyai_cli_client.py`，用无 shell 子进程执行固定版本 `flyai search-flight` / `search-train`。
- API Key 仅通过子进程环境传递，不能出现在 argv、日志和异常。
- 禁止请求时使用 `npx -y`；新增固定版本 Node package/lockfile 或发布阶段安装步骤。
- 对输入做白名单和长度校验，argv 每个参数独立传递，禁止拼接命令字符串。
- 总超时后终止当前子进程并回收资源；并发受 Provider QPS 与 single-flight 约束。
- stdout 必须是唯一完整 JSON；校验 `status == 0`、`message` 和 `data.itemList`。
- 非零退出、stderr异常、超时、JSON截断、体验模式提示或 schema 漂移全部 fail-closed。
- 不允许因 Windows 下“成功 JSON 后 libuv assertion”而忽略 exit code；必须锁定能在目标环境稳定 exit 0 的版本/平台。
- 日志只记录 source_id、命令类型、耗时、退出分类、item数和响应哈希，不记录 Key、完整 URL 或原始 stdout。

## 4. FlyAI Provider

### 4.1 航班

- 将 `FlightSearchScope` 的中文城市名传给 `search-flight`，支持日期、直达/中转、舱位和排序参数。
- 解析 `journeys[].segments[]` 为完整 `FlightOfferSegment`；校验航班号、实际机场、时刻、顺序和中转衔接。
- 精确解析 `ticketPrice`，兼容官方文档 `adultPrice`；使用 `Decimal` 转人民币分，禁止 float。
- item 必须同时具有精确价格、舱位、至少一段、合法 `jumpUrl` 才生成 `FlightOffer`。
- cabin option 只表达响应中实际返回的舱位；不得推断余票数量。
- 第一阶段限定中国大陆且使用 `Asia/Shanghai`；无法确定时区的国际航班返回明确 unsupported。

### 4.2 铁路

- 解析车次、实际车站、出发/到达时间、耗时、席别和 `jumpUrl` 为 `RailOffer`。
- `price` 只接受精确金额；`3xx/5xx`、区间或空值以 `FLIGGY_PRICE_NOT_EXACT` 拒绝。
- 每个 item 只物化响应提供的席别，不补造其他席别或数量。
- 泛化 `build_enabled_rail_providers()`，不再硬编码只允许 `rail_12306_public_query`。

### 4.3 聚合与失败语义

- 航班和铁路均将 FlyAI 纳入现有 Provider outcome；稳定区分 EMPTY、RATE_LIMITED、TIMEOUT、FAILED、INVALID_RESPONSE、PRICE_NOT_EXACT、DISABLED。
- FlyAI 失败时不调用已弃用航司或 12306，不把失败改写成“没有航班/车次”。
- 相同规范化查询使用 60 秒短缓存与 single-flight；缓存内容包含 fetched_at、response hash 和 item fingerprint。

## 5. `jumpUrl` 与合同

- 为内部 `FlightOffer` / `RailOffer` 增加 provider booking reference，包含合法化后的 FlyAI `jumpUrl`、item fingerprint 和获取时间。
- 构造计划时生成 plan-bound `BookingRedirect`；一个 redirect 只能对应产生它的 item/segment。
- `DataSourceType` 增加 `OTA`；redirect type 增加 `FLIGGY`。
- schema version 升级为 `1.18`，同步：
  - `backend/app/models/schemas.py`
  - `schemas/*.schema.json`
  - `frontend/src/types/index.ts`
  - `docs/API_CONTRACT.md`
- `/api/redirect/booking` 从持久化计划读取 FlyAI redirect，不接受客户端 URL；校验 HTTPS、host allowlist、过期时间和 plan/segment 归属。
- 前端铁路/航班 CTA 统一请求 `FLIGGY`，文案为“去飞猪核价并预订”；不再请求 `AIRLINE` 或 `RAIL_12306`。
- redirect 不可用时给出手动打开飞猪核验说明，不降级到航司或12306。

## 6. 运行退役

- 在 FlyAI adapter、合同和回归同一次发布中移除旧票务查询源的默认注册与配置段。
- 默认启动不再要求 `browser_worker`；清理仅服务航司查询的启动说明和运行脚本引用。
- 旧 provider 代码只有在确认无测试/迁移引用后才删除；不得留下可被配置重新启用的未知半成品。
- 旧持久化计划继续可读；旧 redirect 类型不改写为 FlyAI，新规划只生成 `FLIGGY`。

## 7. 目标文件

- `backend/app/data_sources/flyai_cli_client.py`（新增）
- `backend/app/data_sources/fliggy_flyai_provider.py`（新增）
- `backend/app/data_sources/config_loader.py`
- `backend/app/data_sources/provider_registry.py`
- `backend/app/data_sources/flight_providers.py`
- `backend/app/data_sources/rail_providers.py`
- `backend/app/data_sources/redirect_providers.py`
- `backend/app/services/planner.py`
- `backend/app/models/schemas.py`
- `frontend/src/types/index.ts`
- 前端 CTA/API client 消费位置
- `.env.example`、依赖 lockfile、启动/部署说明
- `docs/API_CONTRACT.md`、`docs/PROJECT_INDEX.md`、`docs/Dev/code_change_log.md`
- 对应后端、前端和 smoke 测试

## 8. 实现顺序

1. 增加脱敏 fixture、配置和 CLI client 红灯测试。
2. 实现 CLI client 与退出/超时/Secret 门禁。
3. 实现航班、铁路解析和精确金额转换。
4. 将 provider 接入现有 Planner，保留门到门接驳、约束和推荐逻辑。
5. 升级 1.18 合同并贯通 plan-bound `FLIGGY` redirect。
6. 用正式 Key 执行低频真实 smoke 和 50 样例 benchmark。
7. 验收通过后，在同一切换提交移除旧票务源运行注册和 browser worker 默认依赖。
8. 运行后端全量测试、前端测试/typecheck/export、schema diff、secret scan 和配置检查。

## 9. 验收门禁

- 正式 Key 响应不含体验模式提示；航班和铁路路线卡字段完整。
- 铁路遮罩价格不会进入计划，正式 Key 至少在批准样例中返回可用精确价格。
- `jumpUrl` 与对应路线/价格 item fingerprint 一致，点击后跳转飞猪对应搜索或商品页。
- FlyAI 错误不触发航司或12306请求，不生成模拟事实。
- 固定 CLI 版本在目标环境成功调用 exit 0；Windows libuv assertion 未解决时该环境不能通过。
- Key 不出现在 Git diff、日志、SQLite、API响应、测试产物或进程参数。
- 50 样例记录 cold/warm P50/P95/P99；首个可用卡目标不超过3秒，未达到则任务标记性能门禁未通过。
- 默认 `TRAVEL_DATA_SOURCE_IDS` 中不再存在旧航司/12306查询源。

## 10. 回滚

- FlyAI 切换作为原子发布单元回滚：恢复上一版本代码和上一版环境注册清单。
- 新版本不保留自动航司/12306 fallback；FlyAI 故障只能返回透明失败/重试状态。
- 回滚不得删除新 schema 已持久化的历史计划；旧服务必须忽略无法消费的 1.18 新记录或通过版本边界安全拒绝。
