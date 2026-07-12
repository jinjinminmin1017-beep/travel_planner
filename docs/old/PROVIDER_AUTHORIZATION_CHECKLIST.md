# Provider 授权与配置清单

更新日期：2026-07-04

## 航班报价：航司官方公开前端采集

首批 source_id：

- `airline_mu_public_query`：东航官方公开前端查询源。
- `airline_cz_public_query`：南航官方公开前端查询源。
- `airline_sc_public_query`：山航官方公开前端查询源。

本项目只读取官方公开前端返回的航班报价事实，不登录、不绕验证码、不逆向强认证、不下单、不支付、不抢票。Provider 只返回同时具备真实价格和可售/有限可售信号的 offer；缺价、无可售信号、源站不可用或解析失败时阻断对应航班方案。

启用前审查步骤：

1. 由项目所有者确认源站是航司官方公开入口，并记录可访问页面、条款、robots/频率边界和用途。
2. 确认查询链路无需登录、验证码、强认证签名、客户端私有协议、订单会话或支付状态。
3. 将源站 base URL 加入代码 allowlist；默认仅允许对应航司官网域及子域。
4. 将 `TRAVEL_SOURCE_*_LICENSE_STATUS` 设为 `APPROVED`，并把 `QPS_LIMIT` 维持在低频值。
5. 只在手动确认源站合规后运行 flight live smoke；CI 默认不访问真实航司报价源。

运行配置示例：

```dotenv
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_ENABLED=true
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_LICENSE_STATUS=APPROVED
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_QPS_LIMIT=1
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_COMMERCIAL_ALLOWED=false
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_BASE_URL=https://<approved-ceair-host>
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_SEARCH_PATH=/api/flight/search
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_USER_AGENT=AITravelPlanner/0.1 public-airline-query
TRAVEL_SOURCE_AIRLINE_MU_PUBLIC_QUERY_CACHE_TTL_SECONDS=60
```

注意：

- `.env` 不得提交到 Git。
- `fallback_source_id` 必须为空；航班核心事实缺失时应阻断方案。
- 不展示精确余票数量，除非源站明确返回且后续单独确认展示策略。
- OpenSky、天气、机场状态和测试 fixture 不得冒充航班报价、可售状态或余票事实。
- 前端仍需提示最终价格与可售状态以航司或官方购票平台为准。

## 中国铁路：12306 公开匿名查询

依据：

- 12306 公开查询入口：https://kyfw.12306.cn/otn/leftTicket/init
- 12306 官方公告：https://www.12306.cn/mormhweb/zxdt/202412/t20241211_43192.html

本项目铁路事实源限定为 `rail_12306_public_query`：

- 只访问 12306 面向公众的匿名余票查询页面/H5 相关能力。
- 通过本地站点目录中的电报码查询车次、出发/到达时刻、席别和票价。
- Provider 只返回有可用席别且能解析出票价的车次；缺价、无票、站点码缺失、频率限制或页面结构变化时阻断对应铁路方案。
- `SeatOption.availability` 保留为后端内部筛选兼容字段，App 不展示余票状态或数量。
- 不需要密钥，也不保存账号、cookie、token 或实名乘客信息。

禁止边界：

- 不登录 12306。
- 不绕验证码。
- 不逆向签名、加密、非公开接口或客户端私有协议。
- 不占票、不下单、不支付、不抢票。
- 不接入代售、抢票或购票平台代理能力。
- 不把测试 fixture、估算价或旧模板作为铁路方案兜底。

运行配置：

```dotenv
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_ENABLED=true
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_LICENSE_STATUS=APPROVED
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_QPS_LIMIT=1
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_MIN_INTERVAL_SECONDS=1
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_CACHE_TTL_SECONDS=60
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_COMMERCIAL_ALLOWED=false
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_BASE_URL=https://kyfw.12306.cn
TRAVEL_SOURCE_RAIL_12306_PUBLIC_QUERY_USER_AGENT=AITravelPlanner/0.1 public-12306-query
```

官方跳转：

- `rail_12306_redirect` 继续保留，只用于打开 12306 官方入口。
- 跳转不表达自动登录、自动下单、自动支付或抢票。
- 跳转失败时只返回人工操作说明，不生成替代购票链接。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\check_real_api_config.py
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider rail
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider flight
.\.venv\Scripts\python.exe -m pytest backend\app\tests
```

说明：

- `--provider rail` 是低频手动 live smoke，默认 CI 不调用 12306 实时查询。
- `--provider flight` 只在航司官方公开采集源完成源站审查、allowlist 配置和显式启用后手动运行。
- 后端单测使用 fake HTTP client 覆盖 12306/航司采集解析、缺价阻断、无票/无可售信号阻断和限频语义；这些 fixture 不得进入运行时 fallback。
