# 其余 9 家航司匿名查询验证

验证时间：2026-07-18（Asia/Shanghai）

## 判定口径

- 先通过真实浏览器完成官网匿名查询，确认用户侧确实能够看到航班、票价和舱位。
- 再以项目后端的普通 HTTP 客户端复现，不复用浏览器 Cookie，不注入登录态，不绕过验证码或风控。
- 只有后端能够稳定获得并解析真实结果，才登记 adapter、加入 `.env` 并标记为技术可用。

## 验证结果

| 航司 | 浏览器匿名结果 | 后端直接复现 | 结论 |
| --- | --- | --- | --- |
| 中国国航 CA | `BJS -> SHA`、2026-07-23，官网显示 CA1507 等航班及价格 | `POST /gateway/api/flight/list` 的 `params` 是前端动态加密串，并依赖动态 `x-device-token` | 浏览器可用；后端未启用 |
| 东航/上航 MU/FM | `SHA/PVG -> TAO`、2026-07-19，显示 MU6863、FM9229 等航班及价格 | `POST /portal/v3/shopping/briefInfo` 为明文 JSON，但普通 HTTP 请求被 WAF 返回 403 | 浏览器可用；后端未启用 |
| 南航/重庆航 CZ/OQ | `BJS -> CAN`、2026-07-23，显示 CZ3116 等航班及价格 | `POST /portal/main/flight/direct/query` 的普通 HTTP 响应是阿里云 WAF JavaScript challenge | 浏览器可用；后端未启用 |
| 海航及同站销售航班 HU/Y8 | `BJS -> SHA`、2026-07-23，显示 HU7613、HU7601、HU7603、HU7605、HU7607、Y87596 | 同一匿名 HTTP 会话通过 deep-link GET、redirected POST、`processSearch.do` POST 三步返回结构化航班和舱价 | 已实现并启用 `airline_hu_public_query` |
| 深圳航空 ZH | `SZX -> PEK`、2026-07-23，显示 ZH9101、ZH9111 等航班及价格 | 普通 HTTP 请求 `flightSearch.action` 返回 418，依赖浏览器指纹环境 | 浏览器可用；后端未启用 |
| 四川航空 3U | 匿名查询表单可提交 | 查询结果页返回“当前访问的人太多了，请稍后查询”，同时加载风险验证码脚本 | 本轮未取得可用结果；后端未启用 |
| 吉祥航空 HO | `SHA -> BJS`、2026-07-19，浏览器可进入结果和低价日历 | `POST /api/flightFares/queryFlightSimple` 依赖动态 `blackBox`；缺失时返回 `QUICK_VERIFY_FAIL` | 浏览器可用；后端未启用 |
| 青岛航空 QW | `TAO -> TFU`、2026-07-20，显示 QW9771、08:00-11:05、经济舱 ¥699 | 匿名初始化接口返回计算参数，按官网前端公开算法生成请求材料后，`POST /api/ewp/sales/v1/air/list` 直接返回 JSON | 已实现并启用 `airline_qw_public_query` |
| 山东航空 SC | `TNA -> XMN`、2026-07-19，显示 SC8409、SC8411、SC8407、SC8415 等航班及价格 | `POST /tRtApi/flight/resultSets` 需要动态 `device-id`、`finger_key` 等浏览器风控材料；缺失时返回 400 | 浏览器可用；后端未启用 |

## 项目 Provider 在线验收

以下结果由项目新 adapter 直接请求官网得到，不使用浏览器会话：

- `airline_hu_public_query`：`BJS -> SHA`、2026-07-23，返回 6 个可售 offer：Y87596、HU7607、HU7605、HU7613、HU7601、HU7603；解析后的含税最低总价为 CNY 550.00。
- `airline_qw_public_query`：`TAO -> TFU`、2026-07-20，返回 QW9771；经济舱价格为 CNY 699.00，并返回 34 个官网舱价选项。

## 安全与运行约束

- 两个新源均使用 host allowlist、1 QPS、60 秒超时和 60 秒缓存。
- 海航快照会删除长加密串、会话字段和动态不透明材料后再写入 SQLite；规范化 offer 只保留航班、机场、时刻、价格、舱位和余量证据。
- 遇到 HTTP 429、验证码、风控挑战、非法 host、业务错误或无法解析的响应时 fail-closed，不尝试绕过。
- 其余航司不写入 `.env`；将许可状态改成 `APPROVED` 仍不能替代缺失的稳定后端技术实现。
