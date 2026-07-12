# 真实 API 接入清单与优先级

状态：真实 Provider 渐进接入中，后端业务路径不得使用模拟交通事实兜底。

更新日期：2026-07-04

授权申请与配置步骤见 `docs/PROVIDER_AUTHORIZATION_CHECKLIST.md`。

## 1. 当前边界

允许：

- 使用官方、授权、公开免凭证或用户自有凭证的数据源。
- 铁路事实源仅使用 `rail_12306_public_query` 读取 12306 公开匿名查询页面/H5 相关能力，并保留 `rail_12306_redirect` 作为官方手动跳转入口。
- 航班报价事实源仅使用已审批的航司官方公开前端采集源，例如 `airline_mu_public_query`、`airline_cz_public_query`、`airline_sc_public_query`；offer 必须同时具备真实价格和可售/余票信号。
- 通过 Adapter 接入地图路线、航班报价、航班动态、天气风险、12306 公开铁路查询、官方跳转和 LLM。
- 真实 Provider 失败、未授权、缺 key、限流或返回空结果时，返回业务错误、`SourceFailure`、降级状态或阻断对应方案。
- 自动化测试使用显式 fake provider fixture，但不得在业务路径中静默伪造交通事实。

禁止：

- 从网上搜集、复制或填入他人泄露的 API key、token、cookie。
- 逆向 12306、航司、地图或票务平台，绕验证码、逆向签名/加密或复用非公开接口。
- 自动登录、抢票、占票、下单、支付。
- 保存第三方账号、密码、cookie、token。
- 让 LLM 生成车次、航班、价格、余票、路线、跳转链接等事实字段。

## 2. 已登记数据源

| source_id | 类型 | 当前状态 | 默认启用 | 说明 |
|---|---|---:|---:|---|
| `internal_calc` | INTERNAL_CALCULATION | 已配置 | 是 | 费用汇总、风险、推荐等确定性内部计算。 |
| `osrm_route` | MAP | Adapter 已实现并 live smoke 调通 | 是 | 公开 OSRM Route Service，只读路线距离/耗时；生产建议自托管或改用授权商业地图。 |
| `nominatim_geocode` | MAP | Adapter 已实现并 live smoke 调通 | 是 | Nominatim Search API；用于文本地点解析，公共实例需设置 User-Agent 并低频调用。 |
| `amap_route` | MAP | Adapter 已实现 | 否 | 高德路线规划；需要用户自有 key 与授权。 |
| `baidu_map_route` | MAP | Adapter 已实现 | 否 | 百度 Direction Lite；需要用户自有 key 与授权。 |
| `opensky_states` | FLIGHT | Adapter 已实现并 live smoke 调通 | 是 | OpenSky aircraft states；只用于航班动态/风险辅助，不提供票价或余票。 |
| `open_meteo_forecast` | WEATHER | Adapter 已实现并 live smoke 调通 | 是 | Open-Meteo 天气预报；用于天气风险辅助，不提供交通票价、余票或路况。 |
| `airline_mu_public_query` | FLIGHT | Adapter 已实现；待源站审批 | 否 | 东航官方公开前端采集；只返回有真实价格且有可售/余票信号的舱位，不登录、不下单、不支付。 |
| `airline_cz_public_query` | FLIGHT | Adapter 已实现；待源站审批 | 否 | 南航官方公开前端采集；只返回有真实价格且有可售/余票信号的舱位，不登录、不下单、不支付。 |
| `airline_sc_public_query` | FLIGHT | Adapter 已实现；待源站审批 | 否 | 山航官方公开前端采集；只返回有真实价格且有可售/余票信号的舱位，不登录、不下单、不支付。 |
| `rail_12306_public_query` | RAIL | Adapter 已实现 | 是 | 12306 公开匿名余票查询能力；按站点电报码查询车次、时刻、席别和票价，只返回有可用席别且有票价的铁路 offer；不登录、不绕验证码、不下单、不支付、不抢票。 |
| `rail_12306_redirect` | RAIL | Redirect 已实现并 live smoke 调通 | 是 | 12306 官方入口跳转；不逆向、不登录、不下单。 |
| `airline_official_redirect` | FLIGHT | Redirect 已实现并 live smoke 调通 | 是 | 航司官网跳转。 |
| `amap_uri_redirect` | MAP | Redirect 已实现并 live smoke 调通 | 是 | 高德导航 URI 跳转。 |
| `baidu_uri_redirect` | MAP | Redirect 已实现 | 否 | 百度地图 URI 跳转。 |
| `real_llm` | LLM | OpenAI-compatible wrapper 已实现 | 否 | 未启用或输出非法时不生成三张推荐卡；LLM 仍不得生成事实字段。 |

## 3. 优先级

| 优先级 | 领域 | 数据源 | 当前决策 |
|---|---|---|---|
| P0 | 数据源治理 | `DataSourceConfig`、`DataSourceRuntimeStatus`、`SourceFailure` | 已建立基础状态、缺密钥降级与启用规则；铁路没有默认兜底。 |
| P0 | 地图/本地接驳 | `osrm_route`、高德、百度 | OSRM 已调通；高德/百度等拿到用户自有 key 后联调。 |
| P0 | 地点解析 | `nominatim_geocode`、高德地理编码、百度地理编码 | Nominatim 已调通；生产建议自托管或改用授权商业地理编码。 |
| P1 | 铁路车次/时刻/席别/票价 | `rail_12306_public_query` | 使用 12306 公开匿名查询结果；车次必须同时具备可用席别和票价才进入 Planner。缺站点码、无票、缺价、限流或页面变更均阻断对应铁路方案。 |
| P1 | 航班报价 | 官方公开航司采集源 | Adapter 已实现；缺源站审批、allowlist base URL 或可售价格信号时暂不启用并阻断航班方案。 |
| P1 | 航班动态 | `opensky_states`、飞常准/航司 | OpenSky 已调通；商业风险数据待授权。 |
| P1 | 天气风险 | `open_meteo_forecast`、机场天气 API | Open-Meteo 已调通，可作为天气风险辅助数据。 |
| P2 | 官方跳转 | 12306、航司官网、地图 URI | 已调通 redirect-only，保持交易边界。 |
| P4 | 真实 LLM | OpenAI-compatible API | 需要用户自有 key；启用后仍走 Schema 和语义校验。 |

## 4. 验证命令

```powershell
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider map --provider geocode --provider flight-status --provider weather --provider redirect
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider rail
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider flight
.\.venv\Scripts\python.exe scripts\check_real_api_config.py
.\.venv\Scripts\python.exe -m pytest backend\app\tests
```

说明：

- `map`、`geocode`、`flight-status`、`weather`、`redirect` 当前可在无用户私钥的情况下用合法公开/官方入口做默认 live smoke。
- `rail` 会触发低频 12306 公开实时查询，默认 CI 不运行；只在手动确认需要验证公开查询链路时单独执行。
- `flight` 需要显式启用并审批通过的官方公开航司采集源；缺 allowlist base URL、缺价、无可售信号或源站不可用时应失败而不是补造报价。
- `check_real_api_config.py` 的 secret 档仅检查需要密钥的商业 Provider；`rail_12306_public_query` 不需要密钥，但必须遵守低频、只读、公开匿名边界。
