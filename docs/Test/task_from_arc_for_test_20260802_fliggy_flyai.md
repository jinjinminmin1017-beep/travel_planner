# TEST-20260802-01 飞猪 FlyAI 唯一票务事实源验收

来源：`docs/Dev/task_from_arc_for_dev_20260802_fliggy_flyai.md`。

状态：待测试。

## 1. 配置与 Secret

- 缺 `TRAVEL_SOURCE_FLIGGY_FLYAI_API_KEY` 且 source enabled 时启动 fail-fast，错误只显示变量名，不显示其他 Secret。
- `.env.example` 的 Key 为空，真实 `.env` 被 git ignore；secret scan 覆盖日志、SQLite、测试产物和 Git diff。
- API Key 只进入子进程环境，不出现在 argv、进程列表、stdout/stderr日志或 API 响应。
- 未固定 CLI 版本、运行时依赖 `npx -y` 或 executable 不存在时配置门禁失败。

## 2. CLI Client

- fixture 覆盖成功 JSON、业务 status 非0、空 itemList、非法 JSON、截断输出、stderr异常、超时、非零退出和进程取消。
- 成功必须同时满足完整 JSON、`status=0` 和进程 exit 0；不能接受“JSON成功但 libuv assertion/exit 1”。
- 参数通过独立 argv 传递；包含引号、分号、换行或超长城市名时被校验拒绝，不发生命令注入。
- 并发相同查询只有一个 CLI 进程；缓存命中不启动进程；不同查询服从 QPS 上限。

## 3. 航班解析

- 直达和两段中转 fixture 均生成正确 segments、航班号、实际机场、跨日时刻、舱位、精确价格和 item fingerprint。
- `ticketPrice` 与 `adultPrice` 分别覆盖；小数金额使用 Decimal 转分，无 float 误差。
- 缺航班号、机场、时间、舱位、价格或 `jumpUrl` 时 item fail-closed。
- 相邻机场不一致、时间倒序或中转不合法时拒绝；国际时区未支持时返回明确错误。

## 4. 铁路解析

- 精确 `price`、车次、车站、时刻、席别和 `jumpUrl` 生成完整 `RailOffer`。
- `3xx`、`5xx`、区间、空值和详情页见价均返回 `FLIGGY_PRICE_NOT_EXACT`，不能产生正常计划。
- 只生成响应提供的席别，不推断其他席别、余票或价格。
- 跨日动车/高铁时刻和车站码映射正确。

## 5. Planner 与失败语义

- FlyAI 航班和铁路 offer 继续经过门到门接驳、约束、费用、风险和推荐门禁。
- FlyAI 有 offer 时路线卡来源为 `fliggy_flyai`；空、限流、超时、结构错误和遮罩价格分别显示准确说明。
- FlyAI 失败期间断言航司、browser worker 和12306真实查询调用数为0。
- 同一响应存在一类成功、一类失败时使用正确 PARTIAL；两类都失败时不伪装成 NO_MATCH/EMPTY。

## 6. Redirect 与前端

- schema version 为1.18，`DataSourceType.OTA` 和 `redirect_type=FLIGGY` 在后端、JSON Schema和前端类型一致。
- 每个 redirect 与 plan、segment、item fingerprint 一致；不能把另一 item 的价格和链接组合。
- 客户端不能提交任意 URL；非 HTTPS、非飞猪 allowlist、过期或不属于 plan 的链接被拒绝。
- 航班和铁路 CTA 均显示“去飞猪核价并预订”，点击调用 `FLIGGY`；无链接时显示手动核验，不跳航司或12306。
- Android/iOS/Web 下跳转和返回 App 正常，loading、失败、重复点击保护完整。

## 7. 真实 Key 与性能验收

- 仅在本地获准环境使用用户 `.env` 中正式 Key；CI 默认使用 fixture，不访问真实 FlyAI。
- 航班与铁路各执行至少50个低频样例，覆盖直达、中转、跨日、多机场/车站、空结果；保存脱敏统计，不保存 Key和完整 jumpUrl。
- 正式响应不得含体验模式提示；铁路至少对批准样例返回精确价格。
- 记录 CLI cold/warm、Provider、首个完整计划的 P50/P95/P99；3秒目标未达到则测试结论为性能门禁未通过。
- 真实 smoke 遇到限流、协议变化、商业权限提示或非零退出立即停止，不通过高频重试绕过。

## 8. 退役与回归

- 默认 `TRAVEL_DATA_SOURCE_IDS` 只保留 FlyAI 票务源，不含旧航司和12306查询/redirect源。
- 默认启动不启动 browser worker；旧 Provider 不能通过遗留 ENV 被意外恢复。
- 运行后端全量测试、schema export/diff、配置检查、前端测试/typecheck及 Web/iOS/Android Expo export。
- 旧1.17计划可安全读取或明确拒绝重算；不会被错误赋予 FlyAI redirect。

## 9. 通过标准

- 结构化航班/高铁卡、精确价格门禁、plan-bound FlyAI跳转、唯一供应商失败语义和Secret保护全部通过。
- 没有航司/12306回退、没有模拟事实、没有跨item串链、没有Key泄露。
- CLI固定版本在目标生产环境成功退出0，正式Key配额和商业上线条件已取得可审计确认。

