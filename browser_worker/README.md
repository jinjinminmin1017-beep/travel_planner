# Browser Flight Worker

独立 Node.js/Playwright 进程，为后端提供仅限 loopback 的航司官网匿名查询接口。第一阶段只注册东航/上航 `airline_mu_browser_query`；不登录、不绕过验证码、不复制或持久化 Cookie、设备指纹、风控 Token 和动态加密材料。

## 安装与启动

```powershell
Set-Location browser_worker
npm install
npx playwright install chromium
npm run build
npm run start
```

也可从项目根目录运行：

```powershell
.\scripts\dev.ps1 -Target browser-worker
```

`npm run start` 会读取项目根目录已有的 `.env`。worker 必须只监听 `127.0.0.1`、`localhost` 或 `::1`；后端也会再次验证 worker URL 和 host allowlist。

## 配置

- `BROWSER_WORKER_HOST`：默认 `127.0.0.1`，只允许 loopback。
- `BROWSER_WORKER_PORT`：默认 `4319`。
- `BROWSER_WORKER_SOURCE_IDS`：第一阶段固定 `airline_mu_browser_query`。
- `BROWSER_WORKER_HEADLESS`：默认 `true`。
- `BROWSER_WORKER_EXECUTABLE_PATH`：可选；目标机已有 Chrome/Chromium 时填写其绝对可执行文件路径，可避免依赖在线下载。路径不存在或不是绝对路径时启动失败。
- `BROWSER_WORKER_CACHE_TTL_SECONDS`：60-180 秒，默认 90 秒。
- `BROWSER_WORKER_RESPONSE_TIMEOUT_MS`：业务响应等待，默认 15000 毫秒。
- `BROWSER_WORKER_TOTAL_TIMEOUT_MS`：单次总超时，默认 20000 毫秒。
- `MU_RESULT_URL_TEMPLATE`：经真实浏览器确认的东航结果页 URL 模板；默认 `https://www.ceair.com/zh/cny/shopping/oneway/{origin_iata}-{destination_iata}/{departure_date}`，仍可由部署配置覆盖；覆盖值必须是 HTTPS 东航域名且不得残留未知占位符。

worker 优先等待已确认的 `briefInfo` 业务响应，同时接受官网已渲染的结果卡作为完成信号。DOM 解析会核对结果页航线和日期、切换并确认“现金-含税”，只读取 `.shopping-simple` 中的 MU/FM 航班、时刻和三类公开舱价；页面结构、价格口径或路线不一致时 fail-closed。

## 低频验收

`BROWSER_WORKER_BENCHMARK_CASES` 必须是 JSON 数组，且至少包含 `BROWSER_WORKER_BENCHMARK_REQUESTS` 个互不重复的 `{origin_iata,destination_iata,departure_date}`。验收工具拒绝重复用例，避免 90 秒缓存把同一次官网查询伪装成多次成功：

```powershell
npm run benchmark
```

工具默认在每次查询完成后额外等待 10 秒，逐次只输出路线、日期、成功状态、结果数和非敏感耗时，最终计算成功率、P50/P95/P99、挑战数和缓存命中数。连续 3 次失败或熔断打开时会提前停止，避免持续请求官网；未完成 50 次、成功结果为空、成功率低于 95%、出现缓存命中、P50 超过 8 秒或 P95 超过 15 秒时均退出失败。许可审批和目标环境 50 次验收全部通过前，后端 `airline_mu_browser_query` 必须继续保持禁用。

## 内部接口

- `GET /health`：浏览器连接、会话、队列深度、browser/context/page 分级重建次数，以及每个航司的成功率、空结果率、挑战率和 cold/warm P50/P95/P99。
- `POST /v1/flight-search`：严格校验 source、IATA、日期、人数、币种和结果上限；只返回规范化航班、舱价、阶段耗时与非敏感 evidence ID。

worker 不返回原始响应、Cookie、Token、完整请求头或设备材料。验证码、WAF、限流、超时和响应结构变化均返回稳定错误，不能转换为“无航班”。

单次总超时会通过 `AbortSignal` 终止后续响应等待和解析，不会把超时操作转换为空成功。handler 可登记官方 host 的 403/418/429/503 文档或业务响应，worker 会优先返回稳定挑战错误并进入既有熔断流程。
