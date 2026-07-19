# 东航浏览器结果页验证（2026-07-19）

## 范围

- 官网：`https://www.ceair.com`
- 匿名、只读查询；未登录、未预订、未提交旅客信息。
- 验证路线：`PVG -> PEK`
- 验证日期：`2026-07-23`

## 已确认事实

1. 单机场结果页可由以下 HTTPS URL 直接进入：

   `https://www.ceair.com/zh/cny/shopping/oneway/PVG-PEK/2026-07-23`

2. 页面顶部显示上海到北京与 2026-07-23，结果卡显示真实 MU 航班。抽样可见 MU5151、MU5155、MU5161、MU5163、MU5165；页面公开价格会随“现金-含税 / 现金-不含税”选择变化。
3. 经页面只读 DOM 检查，结果结构为：

   - 航班卡：`.shopping-simple`
   - 航班号：`.title-flight-no`
   - 出发时刻：`.flight-info-dep-time`
   - 到达时刻：`.flight-info-arr-time`
   - 舱价列：`.cabin-level-item`，顺序与页面表头“经济舱 / 超级经济舱 / 公务/头等舱”一致
   - 不可用舱价显示为 `— —`

4. worker 默认 URL 模板据此固定为：

   `https://www.ceair.com/zh/cny/shopping/oneway/{origin_iata}-{destination_iata}/{departure_date}`

5. DOM 解析在输出前必须再次校验 HTTPS 官方 host、结果页路线和日期，确认“现金-含税”已选中，并仅接受 MU/FM 航班号与正整数分币价格。任何结构或口径不一致均返回可重试错误，不转换为“无航班”。

## 独立 worker 运行结果

- 使用 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` 作为 `BROWSER_WORKER_EXECUTABLE_PATH`，独立 worker 成功预热并监听 `127.0.0.1:4319`。
- loopback API 查询 `PVG -> PEK / 2026-07-23` 成功返回 MU5151、MU5155、MU5161、MU5163、MU5165。含税最低示例为 MU5163/MU5165 的 CNY 550.00；总耗时 3454 ms，导航 456 ms、页面完成 2133 ms、解析 860 ms。
- 50 次不同日期低频批次以每次完成后额外等待 2 秒开始。前 5 次成功且无缓存命中，耗时为 3437、4586、3892、5128、5066 ms（P50 4586 ms，P95 5128 ms）；随后 3 次各在约 15 秒超时，worker 熔断打开。继续请求已停止，没有绕过或高频重试。
- 该批次真实外部尝试为 8 次、成功率 62.5%，不满足 95% 验收门禁。验收工具默认额外间隔已提高到 10 秒，并在连续 3 次失败或熔断时自动提前停止；仍需在风险状态恢复后重新完成完整 50 次。

## 尚未完成

- 许可仍为 `PENDING_REVIEW`，`airline_mu_browser_query` 必须保持 `ENABLED=false`。

本文不保存原始响应、Cookie、Token、设备指纹、完整请求头或 POST body。
