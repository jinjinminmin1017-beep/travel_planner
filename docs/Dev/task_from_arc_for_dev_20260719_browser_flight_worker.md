# ARC-20260719-01 常驻浏览器航班查询与业务响应截获

来源：架构任务，2026-07-19。

完成状态：待开发。

## 1. 背景与目标

国航、东航、南航、深航、吉祥和山航官网均已通过真实浏览器匿名查询得到航班或票价，但普通后端 HTTP 请求会受到动态加密、WAF、浏览器指纹或设备材料校验影响，不能稳定取得可解析的真实结果。

本任务新增常驻浏览器航班查询能力：复用浏览器会话，由每家航司的处理器触发官网查询、匹配本次查询对应的业务响应，并转换为项目现有 `FlightOffer`。不得把 HTTP 风控拒绝页、验证码页或解析失败误判为“无航班”。

第一阶段只实现并验收东航；东航满足性能、稳定性和安全门禁后，再依次扩展国航、南航、深航、吉祥和山航。

## 2. 架构约束

1. 浏览器运行在独立的 `browser_worker` 进程，不在 FastAPI 请求线程中直接创建或共享 Playwright 页面对象。
2. Chromium 在进程启动时创建一次；每家航司使用独立 browser context 和 page，保留该航司匿名会话状态。
3. 同一航司第一阶段并发数固定为 1，通过航司级队列或互斥锁避免响应串线。
4. FastAPI 通过仅限内网或 `127.0.0.1` 的内部接口调用 worker；外部 `/api/travel/*` 契约保持不变。
5. worker 返回脱敏后的统一中间结构，Python Provider 负责最终转换和校验 `FlightOffer`。
6. 继续复用现有 60 秒以上短期缓存、请求合并、SQLite 证据和 fail-closed 规则。
7. 不绕过验证码，不伪造登录态，不记录或持久化 Cookie、风控 Token、设备指纹、动态加密串和完整请求头。

## 3. 目标目录与文件范围

建议新增：

```text
browser_worker/
  package.json
  tsconfig.json
  src/
    server.ts
    contracts.ts
    browser-manager.ts
    session-pool.ts
    errors.ts
    airlines/
      types.ts
      mu.ts
      ca.ts
      cz.ts
      zh.ts
      ho.ts
      sc.ts

backend/app/data_sources/
  browser_worker_client.py
  browser_flight_providers.py
```

需要修改：

- `backend/app/data_sources/config_loader.py`
- `backend/app/data_sources/provider_registry.py`
- `backend/app/data_sources/flight_providers.py`
- `backend/app/tests/test_data_sources.py`
- `backend/app/tests/test_flight_providers.py`
- `.env.example`
- `.env` 仅在对应航司真实验收通过后增加并启用该航司配置
- 部署和启动配置
- `docs/ARCHITECTURE.md`
- `docs/Dev/code_change_log.md`

外部 API 不变，不需要数据库迁移，不需要前端同时修改。

## 4. 内部数据流

```text
FlightSearchRequest
  -> BrowserAirlineFlightProvider
  -> 查询缓存与同请求合并
  -> browser-worker 内部接口
  -> 航司级队列
  -> 常驻 context/page
  -> 触发官网匿名查询
  -> 匹配本次业务响应
  -> JSON/HTML/DOM 解析
  -> 脱敏统一中间结构
  -> Python 校验并转换 FlightOffer
  -> 快照、缓存和 Planner
```

## 5. 航司处理器接口

每家航司必须独立实现并测试以下职责：

```ts
interface AirlineBrowserHandler {
  warmUp(page: Page): Promise<void>;
  triggerSearch(page: Page, input: FlightSearchInput): Promise<void>;
  matchesResponse(response: Response, input: FlightSearchInput): boolean;
  parseResponse(response: Response, page: Page, input: FlightSearchInput): Promise<BrowserFlightResult>;
  detectChallenge(page: Page, response?: Response): Promise<ChallengeResult | null>;
}
```

`matchesResponse` 至少校验：

- 官方 allowlist host 和已确认 path。
- HTTP method 与资源类型。
- 请求中的起点、终点、日期和人数与当前任务一致。
- 响应状态、Content-Type 和最小业务结构。
- 响应不是上一条查询、低价日历、城市列表、埋点或风险验证页。

已确认的优先响应目标：

| 航司 | 优先匹配目标 | 解析兜底 |
| --- | --- | --- |
| 东航 MU/FM | `/portal/v3/shopping/briefInfo` | 结果 DOM |
| 国航 CA | `/gateway/api/flight/list` | 官网解密并渲染后的结果 DOM |
| 南航 CZ/OQ | `/portal/main/flight/direct/query` | 结果 DOM |
| 深航 ZH | `flightSearch.action` 及关联结果请求 | HTML/结果 DOM |
| 吉祥 HO | `/api/flightFares/queryFlightSimple` | 结果 DOM |
| 山航 SC | `/tRtApi/flight/resultSets` | 结果 DOM |

响应体若仍为密文，不得在 worker 中复制、逆向或持久化动态风控材料；应等待官网正常渲染后从 DOM 提取公开展示的航班和票价。

## 6. worker 内部接口

新增内部接口：

```text
POST /v1/flight-search
GET  /health
```

查询请求至少包含：`request_id`、`source_id`、`origin_iata`、`destination_iata`、`departure_date`、`adults`、`currency_code`、`max_results`。

查询响应至少包含：

- `success`
- `source_id`
- 脱敏后的 `flights` 与 `fares`
- `challenge` 或稳定错误码
- `queue_ms`、`navigation_ms`、`response_ms`、`parse_ms`、`total_ms`
- worker 生成的非敏感 `evidence_id`

金额使用 `amount_minor + currency + scale`，禁止 float。时间必须带 Asia/Shanghai 对应的明确时区。

## 7. 生命周期、并发与恢复

1. worker 启动时启动 Chromium，并仅预热已启用航司。
2. 请求完成后保留 context/page，不清除 Cookie 和 LocalStorage。
3. 页面关闭或崩溃时只重建该页面；context 异常时只重建该航司 context；浏览器退出时重启 Chromium 并重建全部会话。
4. 单次查询总超时建议 20 秒；业务响应等待建议 15 秒，最终值以真实 benchmark 为准。
5. 相同航司、航线、日期、人数和币种的在途查询必须合并。
6. 成功结果缓存 60-180 秒；连续失败触发短期熔断，避免持续请求官网。
7. 请求取消后停止等待和解析，但不得直接杀死仍服务其他航司的 Chromium。
8. 页面导航使用 `domcontentloaded` 或目标响应完成条件，禁止使用 `networkidle` 作为查询完成条件。
9. 可以屏蔽图片、字体、媒体和已确认非必要统计请求；不得屏蔽官网核心脚本、Cookie、风控初始化和业务接口。

## 8. Provider 与配置接入

1. 新增 `BrowserWorkerClient`，校验 worker URL 只能指向配置 allowlist 的内部地址，并设置连接、读取和总超时。
2. 新增 `BrowserAirlineFlightProvider`，实现现有 `FlightOfferProvider` 协议。
3. Provider 必须复用现有 `_cache_key`、规范化价格、舱位校验、证据快照和 `FlightProviderSearchResult` 失败语义。
4. 新增 browser 类型的 settings model 和 adapter registry，不得把 browser worker 伪装成普通航司官网 HTTP adapter。
5. 每个航司使用独立 `source_id`；只有实现、真实验收、许可状态和技术门禁全部通过后才允许 `ENABLED=true`。
6. worker 不可用、超时、挑战页、业务结构变化和解析失败均返回明确可重试错误；不得返回虚假 offer。
7. Planner 保持当前降级行为，其他已启用航司 Provider 仍可继续尝试。

## 9. 可观测性与安全

增加以下非敏感指标：

- 每家航司查询次数、成功率、空结果率和挑战率。
- cache hit、in-flight dedup hit、queue depth。
- cold/warm query 的 P50、P95、P99。
- 浏览器、context 和 page 重启次数。
- worker timeout、parse error 和 circuit open 次数。

日志只记录 `request_id`、`source_id`、航线、日期、阶段耗时、结果数量和稳定错误码。不得记录响应全文、Cookie、Token、指纹材料、完整 POST body 或个人信息。

## 10. 开发阶段

### Phase 1：东航原型

1. 建立 worker、内部契约、浏览器生命周期和东航 handler。
2. 使用东航结果页直达 URL，提前注册 `briefInfo` 响应监听，不等待完整页面 load/networkidle。
3. 将真实结果转换为现有 `FlightOffer`，验证价格、航班号、机场和时间。
4. 完成缓存、请求合并、超时、挑战检测、重启恢复和指标。
5. 在低频条件下完成至少 50 次真实查询 benchmark。

### Phase 2：其余航司

东航验收通过后，按国航、南航、深航、吉祥、山航顺序逐家实现。每家必须独立提交测试证据和 benchmark，不得仅复制东航 handler 或批量启用配置。

## 11. 测试要求

至少覆盖：

- 每家 handler 的响应 URL、method、post data 和查询条件匹配。
- 上一次查询响应、低价日历、城市列表和埋点请求不会被误匹配。
- JSON、HTML/DOM、空结果、结构变化、验证码、WAF 和超时处理。
- 同一航司请求串行，不同航司可以独立执行。
- 相同查询合并，缓存命中不触发浏览器导航。
- page/context/browser 崩溃后的分级恢复。
- worker 返回金额、时间、机场、航班号和舱位的严格校验。
- 敏感字段不会写入日志和 SQLite 快照。
- 未注册、未实现或未通过技术门禁的 source_id 无法通过 `.env` 强制启用。
- 现有 9C、HU、QW 和 Planner 回归测试不退化。

## 12. 验收标准

东航 Phase 1 必须同时满足：

- 预热查询 P50 不高于 8 秒，P95 不高于 15 秒；若未达到，提交阶段耗时证据并继续优化，不得直接标记完成。
- 无验证场景下，至少 50 次低频真实查询成功率不低于 95%。
- 返回航班和票价与官网公开结果一致，不存在模拟或补造数据。
- 风控页、验证码、解析失败不会转换成“无航班”。
- worker 或浏览器异常后能够自动恢复，FastAPI 不需要重启。
- 外部 API schema 和前端行为不变。
- 后端相关 pytest、worker 单元/集成测试、类型检查和 lint 全部通过。

其余航司分别满足同等验收标准后，才能在 `.env` 中启用对应 source。

## 13. 风险与回滚

- 风险：官网页面和业务响应结构可能变化；每家航司必须独立版本化处理器和监控。
- 风险：浏览器常驻增加内存、部署和崩溃恢复成本；第一阶段只启用东航并限制并发。
- 风险：Headless 环境与本地可见浏览器表现可能不同；必须在目标部署环境完成真实验收。
- 回滚：将对应 browser source 的 `ENABLED` 设为 `false`，停止 worker；现有 HTTP 航司 Provider、Planner、外部 API 和缓存结构保持不变。
- 回滚不得将挑战页或旧快照作为实时票价继续提供。
