# TEST-20260801-02 约束感知候选与可解释备选验收

来源：`docs/Dev/task_from_arc_for_dev_20260801_constraint_aware_candidates.md`。

状态：待测试。

## 1. 铁路候选截断回归

- 固定至少 8 条按时间升序的 railway offers：前 4 条早于 12:00，后 4 条包含可行和不可行的午后车次。
- `max_plans=4` 时断言上限限制成功完整计划数，不是 Provider 前 4 条。
- 前序 offer 因 earliest departure、接驳失败或地点失败退出后，Planner 继续消费后续 offer。
- 存在门到门可行车次时响应含正常计划，不能是 `NO_MATCH`。
- 全量均不满足时才生成 `NO_MATCH`，最近备选从全量 relaxation reserve 中选择。
- 同一车次不同上下车站的去重和多样性规则稳定，不依赖随机顺序。

## 2. 门到门时间约束

- 构造火车 12:30 发车、首程接驳 60 分钟且含缓冲的计划；若门到门 11:10 出发，应违反 earliest 12:00。
- 构造火车 13:30 发车、门到门 12:10 出发的计划，应满足 earliest 12:00。
- 到达约束使用末程接驳结束时间，不使用干线到站/落地时间。
- earliest/latest 与 time window 不重复产生同一边界 violation。
- 跨日和 Asia/Shanghai 时区比较无回归。
- 必需接驳缺少时间时不得按干线时刻伪装成完整匹配。

## 3. 海航多段解析

- 使用问题响应的最小脱敏 fixture，包含 5 个两段 Flight block。
- 至少 HU7606 `SHA -> PEK` + HU6377 `PEK -> WNZ` 解析为同一 `FlightOffer` 的两个 segment。
- 校验 HU7606 12:10 起飞、HU6377 18:45 起飞以及正确日期、机场和顺序。
- 相邻机场不一致、倒序时间、换乘不足、缺航程级价格、超过段数上限时 fail-closed 并返回准确 reason code。
- 两段 offer 进入 Planner 后生成 `TRANSFER_FLIGHT`，含显式中转等待/接驳，不复制价格。
- 春秋和青岛航真实空结果为 `EMPTY`；海航结构不支持或解析失败不是 `EMPTY`。

## 4. Coverage 与 API

- 三来源全部有效空时航班 coverage 为 `EMPTY`。
- 两个来源空、一个来源解析失败时 coverage 为 `FAILED`，同时保留三个逐来源 outcome。
- 任一来源产生可验证 offer 时航班 coverage 为 `VERIFIED`，其他来源限制仍可解释。
- `NO_MATCH` 继续为 HTTP 200，`plans=[]`、`recommendation_result=null`；正常候选存在时不得生成 `constraint_analysis` 终态。
- schema version 保持 `1.17`，schema export 无 diff，无数据库迁移。

## 5. 前端验收

- 展开备选详情可见门到门时间线、总费用/耗时、车次或航班、接驳、偏差、保留约束和数据来源。
- 风险/完整度只作为带解释的辅助信息，不能再次成为详情唯一内容。
- 显示确认放宽前后的值；展开/收起不触发重新规划。
- 备选详情没有购票按钮；只有确认放宽后才创建新规划请求。
- 航班说明分别展示春秋有效空、青岛航有效空、海航中转结构暂不能核验；不出现笼统“没有航班”。
- 360/390/430 宽度下详情不溢出，长航班号、跨日时间和多 violation 可读。

## 6. 性能与回归

- 90+ offer 预选不对每条调用地图；地图/地理编码调用数受 shortlist 上限约束。
- 固定输入的预选和排序结果确定，不因 Provider 列表顺序抖动。
- 运行后端 planning/constraint/flight/API 测试、前端 helper/UI contract/typecheck 和 Expo export。
- 真实 smoke 仅低频访问已批准公开来源，遇到挑战、限流或协议变化立即停止。

## 7. 通过标准

- 假性 `NO_MATCH`、错误 D3145 唯一备选和海航两段全拒绝三个回归用例全部转绿。
- 门到门时间语义、逐来源覆盖解释和只读备选详情同时通过。
- 无额外高频 Provider 请求、无虚构事实、无外部 schema 变化。
