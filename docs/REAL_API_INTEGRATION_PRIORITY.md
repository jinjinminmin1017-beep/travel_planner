# 真实 API 接入清单与优先级

状态：真实 Provider 渐进接入中，后端业务路径不得再使用模拟交通事实兜底。

日期：2026-06-04

授权申请与配置步骤见 `docs/PROVIDER_AUTHORIZATION_CHECKLIST.md`。

## 1. 当前边界

允许：
- 使用官方、授权、公开免凭证或用户自有凭证的数据源。
- 通过 Adapter 接入地图路线、航班报价、航班动态、天气风险、铁路时刻、授权票务 Partner、官方跳转和 LLM。
- 真实 Provider 失败、未授权、缺 key 或返回空结果时，返回业务错误、数据源失败、降级状态或阻断方案。
- 自动化测试使用显式 fake provider fixture，但不得在业务路径中静默伪造交通事实。

禁止：
- 从网上搜集、复制或填入他人泄露的 API key、token、cookie。
- 逆向 12306、航司、OTA、地图或票务平台。
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
| `amadeus_flight_offers` | FLIGHT | Adapter 已实现 | 否 | Amadeus Flight Offers Search；需要用户自有 client id/secret。 |
| `amadeus_flight_price` | FLIGHT | Adapter 方法已实现 | 否 | Amadeus Flight Offers Price；需要用户自有 client id/secret。 |
| `irail_connections` | RAIL | Adapter 已实现并 live smoke 调通 | 是 | iRail 比利时铁路公开连接/时刻 API；不提供中国铁路票价或余票。 |
| `rail_authorized_partner` | RAIL | 聚合数据 817 Adapter 已实现 | 否 | 铁路时刻、票价、余票授权 Partner；需要聚合数据 key 与授权范围确认。 |
| `rail_12306_redirect` | RAIL | Redirect 已实现并 live smoke 调通 | 是 | 12306 官方入口跳转；不逆向、不登录、不下单。 |
| `airline_official_redirect` | FLIGHT | Redirect 已实现并 live smoke 调通 | 是 | 航司官网跳转。 |
| `amap_uri_redirect` | MAP | Redirect 已实现并 live smoke 调通 | 是 | 高德导航 URI 跳转。 |
| `baidu_uri_redirect` | MAP | Redirect 已实现 | 否 | 百度地图 URI 跳转。 |
| `ota_partner_redirect` | OTA | Redirect 模板已实现 | 否 | 需要合作方模板和参数规范。 |
| `real_llm` | LLM | OpenAI-compatible wrapper 已实现 | 否 | 未启用或输出非法时不生成三张推荐卡；LLM 仍不得生成事实字段。 |

## 3. 优先级

| 优先级 | 领域 | 数据源 | 当前决策 |
|---|---|---|---|
| P0 | 数据源治理 | `DataSourceConfig`、`DataSourceRuntimeStatus`、`SourceFailure` | 已建立基础状态、缺密钥降级与启用规则。 |
| P0 | 地图/本地接驳 | `osrm_route`、高德、百度 | OSRM 已调通；高德/百度等拿到用户自有 key 后联调。 |
| P0 | 地点解析 | `nominatim_geocode`、高德地理编码、百度地理编码 | Nominatim 已调通；生产建议自托管或改用授权商业地理编码。 |
| P1 | 航班报价 | Amadeus Flight Offers / Price | Adapter 已实现；缺用户自有凭证，暂不启用。 |
| P1 | 航班动态 | `opensky_states`、飞常准/航司 | OpenSky 已调通；商业风险数据待授权。 |
| P1 | 天气风险 | `open_meteo_forecast`、机场天气 API | Open-Meteo 已调通，可作为天气风险辅助数据。 |
| P1 | 铁路时刻 | `irail_connections` | 已调通公开铁路时刻；仅证明真实铁路连接 Provider 链路。 |
| P2 | 官方跳转 | 12306、航司官网、地图 URI | 已调通 redirect-only，保持交易边界。 |
| P3 | 铁路票价/余票 | `rail_authorized_partner` | 未授权前不能调用真实票价/余票，也不能用模拟数据伪装。 |
| P4 | 真实 LLM | OpenAI-compatible API | 需要用户自有 key；启用后仍走 Schema 和语义校验。 |

## 4. 验证命令

```powershell
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider map --provider geocode --provider flight-status --provider weather --provider rail-schedule --provider redirect
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider flight
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider rail
.\.venv\Scripts\python.exe scripts\check_real_api_config.py
.\.venv\Scripts\python.exe -m pytest backend\app\tests
```

说明：
- `map`、`geocode`、`flight-status`、`weather`、`rail-schedule`、`redirect` 当前可在无用户私钥的情况下用合法公开/官方入口做 live smoke。
- `flight` 需要 Amadeus 用户自有凭证。
- `rail` 需要铁路授权 Partner 的 `RAIL_PARTNER_BASE_URL=https://apis.juhe.cn/fapigw/train/query` 和 `RAIL_PARTNER_API_KEY`。
- `check_real_api_config.py` 只有在航班报价与铁路票价/余票授权也满足后才会整体通过。
