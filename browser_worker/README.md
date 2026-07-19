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
- `BROWSER_WORKER_CACHE_TTL_SECONDS`：60-180 秒，默认 90 秒。
- `BROWSER_WORKER_RESPONSE_TIMEOUT_MS`：业务响应等待，默认 15000 毫秒。
- `BROWSER_WORKER_TOTAL_TIMEOUT_MS`：单次总超时，默认 20000 毫秒。
- `MU_RESULT_URL_TEMPLATE`：经真实浏览器确认的东航结果页 URL 模板；支持 `{origin_iata}`、`{destination_iata}`、`{departure_date}`、`{adults}`、`{currency_code}`。未配置时东航查询 fail-closed。

`MU_RESULT_URL_TEMPLATE` 不在仓库中猜测默认值。完成目标部署环境的真实页面确认、许可审批和 50 次低频 benchmark 后，才可在部署环境设置模板并启用后端 `airline_mu_browser_query`。

## 内部接口

- `GET /health`：浏览器连接、会话、队列深度和非敏感聚合指标。
- `POST /v1/flight-search`：严格校验 source、IATA、日期、人数、币种和结果上限；只返回规范化航班、舱价、阶段耗时与非敏感 evidence ID。

worker 不返回原始响应、Cookie、Token、完整请求头或设备材料。验证码、WAF、限流、超时和响应结构变化均返回稳定错误，不能转换为“无航班”。
