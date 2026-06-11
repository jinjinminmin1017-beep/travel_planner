# Provider 授权与配置清单

日期：2026-06-04

## 航班报价：Amadeus Self-Service

官方入口：

- https://developers.amadeus.com/
- https://developers.amadeus.com/self-service/apis-docs/guides/moving-to-production-743

本项目只使用 Flight Offers Search 和 Flight Offers Price，不使用下单、出票或支付 API。

申请步骤：

1. 由项目所有者注册 Amadeus for Developers 账户并创建应用。
2. 获取测试环境 `API Key` 和 `API Secret`，仅用于测试环境联调。
3. 在 My Self-Service Workspace 中申请 Production Environment。
4. 由项目所有者填写身份、账单和应用信息，并签署 Amadeus 服务条款。
5. Production 申请通过后，获取生产环境密钥。

测试环境配置：

```dotenv
TRAVEL_SOURCE_AMADEUS_FLIGHT_OFFERS_ENABLED=true
TRAVEL_SOURCE_AMADEUS_FLIGHT_OFFERS_LICENSE_STATUS=APPROVED
TRAVEL_SOURCE_AMADEUS_FLIGHT_OFFERS_QPS_LIMIT=1
TRAVEL_SOURCE_AMADEUS_FLIGHT_PRICE_ENABLED=true
TRAVEL_SOURCE_AMADEUS_FLIGHT_PRICE_LICENSE_STATUS=APPROVED
TRAVEL_SOURCE_AMADEUS_FLIGHT_PRICE_QPS_LIMIT=1
AMADEUS_CLIENT_ID=<test API key>
AMADEUS_CLIENT_SECRET=<test API secret>
AMADEUS_BASE_URL=https://test.api.amadeus.com
```

生产报价配置：

```dotenv
AMADEUS_CLIENT_ID=<production API key>
AMADEUS_CLIENT_SECRET=<production API secret>
AMADEUS_BASE_URL=https://api.amadeus.com
```

注意：

- `.env` 不得提交到 Git。
- 测试密钥和测试环境数据不得标记为生产真实报价。
- Amadeus Self-Service 数据覆盖存在限制，前端仍需提示最终价格与可售状态以航司或购票平台为准。

## 中国铁路票价与余票

铁路 12306 明确表示其平台是互联网票务服务的唯一官方渠道，且从未授权任何第三方平台发售火车票和办理火车票相关业务：

- https://www.12306.cn/mormhweb/zxdt/202412/t20241211_43192.html

因此：

- 不得逆向、抓取或复用 12306 未公开接口。
- 不得把第三方购票、抢票或代售能力接入本项目。
- `rail_12306_redirect` 只能作为官方入口跳转。
- 在取得书面授权和接口规范之前，`rail_authorized_partner` 必须保持禁用。

铁路合作方必须书面确认：

1. 有权向本项目提供列车时刻、票价和余票只读数据。
2. 授权范围允许本项目展示和用于出行方案比较。
3. 数据来源、更新频率、QPS、缓存规则、商用范围和地域范围。
4. 是否允许展示车次、席别、票价、余票状态和经停站序。
5. 不要求本项目保存第三方账号、密码、cookie、token 或实名乘客信息。
6. 不要求本项目执行登录、占票、下单、支付或抢票。

当前通用 Adapter 期望的接口：

```text
GET {RAIL_PARTNER_BASE_URL}/rail/offers
Authorization: Bearer {RAIL_PARTNER_API_KEY}

query:
  train_number
  origin_station
  destination_station
  departure_date
```

响应至少需要：

```json
{
  "data": [
    {
      "train_number": "G123",
      "origin_station": "上海虹桥",
      "destination_station": "青岛北",
      "departure_at": "2026-06-20T09:00:00+08:00",
      "arrival_at": "2026-06-20T15:00:00+08:00",
      "stop_sequence": ["上海虹桥", "青岛北"],
      "seat_options": [
        {
          "option_id": "second_class",
          "seat_type": "二等座",
          "price": "560.00",
          "availability": "AVAILABLE",
          "source_option_version": "partner-version"
        }
      ]
    }
  ]
}
```

取得合同和接口规范后，先调整 Adapter 以匹配真实协议，再配置：

```dotenv
TRAVEL_SOURCE_RAIL_AUTHORIZED_PARTNER_ENABLED=true
TRAVEL_SOURCE_RAIL_AUTHORIZED_PARTNER_LICENSE_STATUS=APPROVED
TRAVEL_SOURCE_RAIL_AUTHORIZED_PARTNER_QPS_LIMIT=<contract limit>
RAIL_PARTNER_BASE_URL=<authorized partner API base URL>
RAIL_PARTNER_API_KEY=<authorized partner API key>
```

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\check_real_api_config.py
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider flight
.\.venv\Scripts\python.exe scripts\live_smoke_real_apis.py --status --provider rail
.\.venv\Scripts\python.exe -m pytest backend\app\tests
```

## 外联状态

2026-06-04 已发送邮件：

- Travelfusion Sales，`sales@travelfusion.com`：询问 `tfFlight` / `tfRail` 是否支持航班报价和中国铁路时刻、票价、余票只读搜索授权。
- Rail Europe Web Services，`webservices@raileurope.com`：询问 B2B API 是否支持中国铁路时刻、票价、余票只读搜索授权。

等待回复内容：

1. 是否覆盖中国铁路。
2. 是否支持 read-only shopping / planning，不绑定下单出票。
3. 授权范围、展示权利、缓存规则和 SLA。
4. 沙箱、文档、认证方式、QPS 和价格。
5. 是否需要商务合同或最低消费。
