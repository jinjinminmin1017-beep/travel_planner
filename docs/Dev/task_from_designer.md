# 路径规划前端落地任务

## 2026-07-27 Approved V2 开发任务（当前有效）

> 本节是当前最新、已由用户确认的 UI 实施任务。若与下方 2026-07-12 的 V1 历史记录冲突，以本节为准。下方已完成记录不得改回未完成状态。

### V2.0 任务状态与设计基准

- 视觉方案：已由用户确认
- 设计批准状态：Approved
- 前端实施状态：已完成（2026-07-27）
- 任务类型：React Native / Expo 前端 UI 重构
- 技术栈：React Native 0.81 + Expo 54 + TypeScript
- 主要入口：`frontend/src/App.tsx`
- 设计 Token：`frontend/src/designSystem.ts`
- 不修改推荐排序、价格计算、数据源治理和外部跳转的业务语义
- 不新增购票、支付或站内交易能力

#### 已批准设计总览

- 核心流程原型：[`travel_flow_optimization_v2.html`](../Design/travel_flow_optimization_v2.html)
- 核心流程效果图：[`travel_flow_optimization_v2.png`](../Design/travel_flow_optimization_v2.png)
- 绝对路径：`C:\Users\儿儿的爹妈\Documents\travel_planner\docs\Design\travel_flow_optimization_v2.png`

#### 已批准单页效果图

- 路程输入页：[`travel_input_v2.png`](../Design/travel_input_v2.png)
- 规划页：[`planning_progress_v2.png`](../Design/planning_progress_v2.png)
- 规划生成页：[`planning_result_v2.png`](../Design/planning_result_v2.png)
- 路线详情原型：[`route_detail_embedded_cost_concept.html`](../Design/route_detail_embedded_cost_concept.html)
- 路线详情效果图：[`route_detail_embedded_cost_mobile.png`](../Design/route_detail_embedded_cost_mobile.png)
- 路线详情说明图：[`route_detail_embedded_cost_concept.png`](../Design/route_detail_embedded_cost_concept.png)

开发必须阅读两份 Approved HTML，并以其中的布局、间距、色彩和信息层级为视觉基准。HTML 仅用于参考，不得直接作为生产页面交付。

### V2.1 页面目标

将“输入需求、等待规划、查看生成方案、核对路线详情”统一为一条连续的移动端任务流：

1. 输入页只突出“描述行程并开始规划”，历史与偏好退到次级。
2. 规划页告诉用户正在处理什么、已完成什么、下一步是什么。
3. 生成页先给推荐结论，再给方案差异、推荐理由和路线骨架。
4. 详情页去除方案风险提示，将费用明细并入路线，并明确席别调整入口和官方跳转去向。
5. 四页保持同一套青绿色 Token、16px 卡片圆角、12px 控件圆角和 48px 触控目标。

### V2.2 建议代码拆分

不得继续扩大 `App.tsx`。建议按现有目录补充或重构以下组件：

```text
frontend/src/components/input/
  TravelInputScreen.tsx
  TripComposer.tsx
  QuickPreferenceActions.tsx
  TripHistorySection.tsx
  RetentionPreferencesSheet.tsx

frontend/src/components/planning/
  PlanningProgressScreen.tsx
  PlanningStageList.tsx

frontend/src/components/results/
  ResultsOverview.tsx
  ResultsHeader.tsx
  RouteSummaryHero.tsx
  PlanSelector.tsx
  RecommendationRationale.tsx
  RouteTimeline.tsx
  ResultsBottomAction.tsx
  RouteDetailScreen.tsx
  JourneyLegCard.tsx
  JourneyCostSummary.tsx
```

建议新增或集中以下纯函数，不得把映射散落在 JSX：

```text
frontend/src/utils/
  presentation.ts 或继续使用 results/presentation.ts
  routePlanning.ts
```

- `buildPlanningStagePresentation(progress)`
- `selectedSegmentPrice(segment)`
- `buildRouteCostPresentation(plan)`
- `buildOfficialRedirectPresentation(plan)`
- `latestPlanUpdatedAt(plan)`

纯展示组件不得直接发请求。继续通过现有 `src/api/client.ts`、页面回调和 `App.tsx` 状态边界完成请求。

### V2.3 路程输入页

目标文件：

- `frontend/src/App.tsx`
- 新增 `frontend/src/components/input/*`

#### 页面结构

1. 顶部显示“出行搭子”，右侧“偏好”按钮。
2. 主标题“今天，想去哪里？”。
3. 说明“一句话告诉我出发地、目的地和时间。”。
4. 单一白色输入面板：
   - 标签“描述你的行程”
   - 多行自然语言输入
   - 快捷操作“使用定位”“明天出发”“少换乘”
   - 主按钮“开始规划”
5. 最近规划默认展示最多 2 条。
6. 保留底部“云起 / 路明”主导航。

#### 交互

- “开始规划”复用现有 `submit`，不得改变自然语言解析链路。
- 空输入点击提交时，保留明确的必填错误提示和输入焦点。
- 提交中禁用按钮并防止重复提交，按钮内显示局部 loading。
- “使用定位”复用现有 `requestLocation`。
- “明天出发”将“明天出发”语义插入当前输入，不覆盖用户已有文本。
- “少换乘”将“希望少换乘”语义插入当前输入，不重复插入相同偏好。
- “偏好”打开原有偏好记忆能力的原生底部面板或独立页面：
  - 常用出发地
  - 目的地偏好
  - 开启/关闭记忆
  - 套用
  - 保存
- 不得删除现有偏好清空语义和隐私说明。
- “查看全部”展开最近规划与收藏方案，或进入同一层级的记录页；不得删除收藏入口。
- 历史摘要必须继续标记为脱敏摘要，不得把它伪装成实时价格。

#### 视觉

- 首屏不得再次同时平铺“最近规划、收藏方案、偏好记忆”三个大模块。
- 输入面板为唯一核心卡片，不嵌套额外卡片。
- 快捷操作为 40-48px 高的次级控件，主按钮为 48px。
- 输入框至少支持 3 行文本，文本放大时允许增高。

### V2.4 规划页

目标文件：

- `frontend/src/components/planning/PlanningProgressScreen.tsx`
- `frontend/src/components/planning/PlanningStageList.tsx`

#### 页面结构

1. 顶部“路明”和“取消规划”。
2. 主标题使用真实候选数量：
   - 有候选数量时：“正在核对 N 个候选方案”
   - 暂无候选数量时：“正在为你规划路线”
3. 显示真实起终点。
4. 继续复用：
   - `frontend/assets/maps/world-map.png`
   - `frontend/assets/maps/world-map-flow.png`
5. 地图下方显示当前具体任务和真实进度百分比。
6. 规划阶段改为纵向四行，不再横向排列。
7. 底部说明“可以离开此页面，规划完成后会保留结果。”

#### 阶段映射

| progress | 阶段文案 | 状态 |
| ---: | --- | --- |
| 0-20 | 理解行程需求 | 进行中 |
| 21-40 | 确认地点和时间 | 进行中 |
| 41-75 | 比对车次与接驳 | 进行中 |
| 76-99 | 评估并生成方案 | 进行中 |
| 100 | 规划完成 | 完成 |

早于当前阶段的行显示“已完成”，晚于当前阶段的行显示“待处理”。

#### 交互和状态

- 进度必须使用服务端 `response.progress`。
- 服务端进度暂缺时可继续使用现有体验进度，但最大停在 95%。
- 点击“取消规划”继续调用现有异步任务取消逻辑。
- 取消中按钮 disabled，禁止重复取消。
- 轮询暂停时保留现有“继续获取 / 取消规划”能力。
- 网络中断不能清空已显示阶段和进度。
- 地图扫光只表达数据汇聚，不表示真实地理线路。
- 开启系统减少动态效果后，停止循环扫光，仅更新静态进度。

### V2.5 规划生成页

目标文件：

- `frontend/src/components/results/ResultsOverview.tsx`
- `frontend/src/components/results/ResultsHeader.tsx`
- `frontend/src/components/results/RouteSummaryHero.tsx`
- `frontend/src/components/results/PlanSelector.tsx`
- `frontend/src/components/results/RecommendationRationale.tsx`
- `frontend/src/components/results/RouteTimeline.tsx`
- `frontend/src/components/results/ResultsBottomAction.tsx`

#### 页面结构

1. 顶部只显示城市级路线标题，例如“上海 → 青岛”，长门牌地址移入时间轴。
2. 显示日期和真实出发时间。
3. 显示“已找到 N 种可行路线”。
4. 右侧更新时间来自最新 `DataSourceMetadata.fetched_at`；缺失时不显示，不得硬编码“刚刚”。
5. 目的地图片与三个核心指标：
   - 预计总价
   - 全程耗时
   - 换乘次数
6. 紧凑方案选择器：
   - 综合推荐
   - 更省时或现有真实产品定义
   - 更省钱
7. 推荐理由必须来自真实方案差异或推荐结果。
8. 路线预览展示关键时间、站点、车次和接驳。
9. 固定底部操作区：收藏、查看完整路线。

#### 业务保持

- 不改变 `RecommendationSlot.recommendation_type` 的既有业务含义。
- 方案不可用时保留槽位，显示真实不可用原因并 disabled。
- 切换方案同步更新图片、指标、推荐理由、时间轴和收藏状态。
- 保留 `RECOMMENDATION_CLICK` 埋点。
- “调整时间”继续打开现有 `ScheduleAdjustPanel`。
- “数据来源”移入顶部更多菜单或保持次级文字入口，不得删除。
- `PARTIAL` 结果继续显示可用路线，并在推荐理由后提供降级提示与“重试来源”。
- 不把长起终点地址同时重复在标题、图片和时间轴中。

### V2.6 路线详情页

目标文件：

- `frontend/src/components/results/RouteDetailScreen.tsx`
- `frontend/src/components/results/JourneyLegCard.tsx`
- 新增 `frontend/src/components/results/JourneyCostSummary.tsx`
- `frontend/src/components/results/PlanRiskNotice.tsx`

#### 页面结构

1. 顶部返回、标题“路线详情”、副标题“综合推荐”、分享。
2. 路线摘要显示起点、终点、出发、抵达和预计总价。
3. 删除页面中的 `PlanRiskNotice` 渲染。
4. 删除标题下方风险等级文案，不再显示“综合推荐 · 低风险”。
5. 分段路线使用一个连续白色容器和共享纵向轨迹。
6. 每段显示：
   - 时间范围
   - 交通方式
   - 起终点
   - 时长、席别或接驳说明
   - 该段费用
   - 估算标记
7. 所有分段之后紧接“路线费用合计”，不再保留独立 `costCard`。
8. 底部固定显示官方确认去向和主按钮。

#### 费用映射

总价唯一权威来源：

```ts
plan.cost_breakdown.total_cost
```

单段价格按以下优先级读取：

1. `RAIL`：`selected_seat_option_id` 对应 `seat_options[].price`
2. `FLIGHT`：`selected_cabin_option_id` 对应 `cabin_options[].price`
3. `LOCAL_TRANSFER`：当前 `option_id` 对应 `transfer_options[].estimated_cost`
4. 无匹配选项时：`segment.estimated_cost`
5. 仍无法归属时：不猜测，不在该段显示虚构价格

`cost_breakdown.items` 当前没有 `segment_id`。不得通过 `label` 文案猜测归属。无法可靠归属的费用项以平面“其他费用”行展示在分段之后、总价之前，仍属于路线容器，不新增嵌套卡片。

#### 席别与舱位调整

- 对存在 `seat_options` 的铁路段，将整行“已选席别 / 当前席别与价格 / 更换席别”做成 48px 可点击入口。
- 对存在 `cabin_options` 的航班段使用同样结构，文案改为“更换舱位”。
- 点击后在当前交通段内展开候选项。
- 当前已选项显示 Selected 并 disabled。
- 选择新席别或舱位继续调用现有 `recalculate`。
- 重新计算期间只锁定相关选择控件，不清空整页。
- 成功后更新分段费用、总价和推荐结果；失败时保留原选择并显示明确错误。
- 不再依赖模糊的“可调整席别”说明文字作为入口。

#### 官方确认

使用 `buildOfficialRedirectPresentation(plan)` 统一返回：

```ts
type OfficialRedirectPresentation = {
  helperText: string;
  buttonLabel: string;
  redirectType: "RAIL_12306" | "AIRLINE";
  segmentId: string | null;
};
```

规则：

- 首个主要交通段为铁路：
  - 提示：“点击后将打开铁路12306官方渠道”
  - 按钮：“前往铁路12306确认”
  - `redirectType = "RAIL_12306"`
- 首个主要交通段为航班：
  - 能从真实数据获得航空公司名称时，按钮显示“前往{航空公司}官网确认”
  - 无航空公司名称时，按钮显示“前往航空公司官网确认”
  - `redirectType = "AIRLINE"`
- 点击后继续调用现有 `bookingRedirect` 和 `openExternalUrl`。
- URL 不可用或无法打开时，继续显示 `fallback_instruction`。
- 文案必须明确：仅确认实时班次、余票和价格，不会自动下单或支付。

#### 现有能力不得丢失

- 分享
- 收藏
- 复制摘要
- 查看数据来源
- 票源增强说明
- 问题反馈
- 返回总览并保持当前方案

以上次级能力可以放在正文后部或更多操作中，但不得从产品中删除。

### V2.7 设计 Token 与样式

继续复用 `frontend/src/designSystem.ts`，不得新增近似重复 Token。

| 角色 | 值 |
| --- | --- |
| 页面背景 | `#eff4f3` |
| 卡片表面 | `#ffffff` |
| 主文字 | `#15282b` |
| 次文字 | `#5d7073` |
| 分隔线 | `#d9e3e1` |
| 主色 | `#126b75` |
| 深主色 | `#0b5159` |
| 浅主色 | `#e4f1ef` |
| 连接线 | `#bfe4dc` |
| 卡片圆角 | `16` |
| 控件圆角 | `12` |
| 小圆角 | `9` |
| 点击热区 | iOS 至少 44pt，Android / 当前跨平台基准使用 48px |
| 页面横向边距 | `16` |
| 卡片内边距 | `12-16` |
| 模块间距 | `16-24` |

字体继续使用系统字体。数字和金额必须单行，长标签一侧允许收缩或换行，不得把金额推出 390px 屏幕。

### V2.8 状态与无障碍

四页必须覆盖：

- normal
- loading
- skeleton
- empty
- error
- network error
- disabled
- selected
- pressed
- expanded / collapsed
- partial result

要求：

- 所有 Pressable 提供准确 `accessibilityRole`、`accessibilityLabel` 和 `accessibilityState`。
- 席别入口读屏示例：“更换高铁席别，当前二等座，票价553元”。
- 方案选择器读屏包含推荐类型、价格或耗时、选中和不可用状态。
- 进度读屏包含当前百分比和当前阶段。
- 底部固定操作区不能遮挡 Home Indicator、系统导航栏或正文末尾。
- Web 端支持键盘 focus、Tab 顺序和 Enter / Space 激活。
- 动画遵守 Reduce Motion / Remove Animations。

### V2.9 适配要求

必须完成以下尺寸视觉回归：

- 360×800
- 390×844
- 393×852
- 430×932

验收要求：

- 无横向滚动和右侧裁切。
- 起终点、总价、耗时、换乘次数完整可读。
- 金额不得换行。
- 长地址最多按组件规则换行，不得扩大 flex 子项的 intrinsic width。
- React Native Web 的 `flex: 1` 文本容器应允许收缩；必要时设置对应最小宽度约束。
- 文本放大 125% 时，按钮文字不截断，方案选择器和列表行允许增高。
- 平板与 Web 使用 `ui.contentMaxWidth` 居中，不把手机布局无约束拉满。

### V2.10 开发顺序

#### Phase V2-1：公共 helper 与输入页

- [x] 新增规划阶段、单段费用、费用汇总和官方跳转展示 helper。
- [x] 为 helper 补充单元测试。
- [x] 从 `App.tsx` 拆出输入页组件。
- [x] 落地输入面板、快捷操作、最近规划和偏好入口。
- [x] 保留收藏、偏好记忆、定位、脱敏摘要和错误处理。

#### Phase V2-2：规划页

- [x] 将规划阶段从横向卡片改为纵向状态行。
- [x] 显示真实当前任务、候选数量和进度。
- [x] 保留取消、继续轮询和网络恢复能力。
- [x] 完成 Reduce Motion 降级。

#### Phase V2-3：规划生成页

- [x] 缩短顶部路线标题，长地址移入时间轴。
- [x] 实现“已找到 N 种可行路线”和真实更新时间。
- [x] 按 Approved V2 重排摘要、方案选择、推荐理由和路线预览。
- [x] 保留数据来源、调整时间、收藏和查看完整路线。
- [x] 验证 COMPLETE、PARTIAL、不可用推荐槽和重试来源状态。

#### Phase V2-4：路线详情

- [x] 移除 `PlanRiskNotice` 渲染和顶部风险等级文案。
- [x] 将单段费用与总价合并进连续路线容器。
- [x] 实现席别 / 舱位整行调整入口和展开状态。
- [x] 实现动态官方渠道提示与按钮文案。
- [x] 保留分享、收藏、复制、来源、票源增强和反馈。
- [x] 验证跳转 URL 可用、不可用和打开失败三种情况。

#### Phase V2-5：测试和视觉回归

- [x] `npm run typecheck`
- [x] `npm run test:helpers`
- [x] `npm run build`
- [x] 更新 `frontend/tests/ui-contract.test.mjs`
- [x] 更新或新增 `frontend/tests/routePlanning.test.mjs`
- [x] 在 360、390、393、430px 生成视觉回归图。
- [x] iOS 与 Android 各验证安全区、系统返回和底部固定操作区。
- [x] 验证文本放大 125% 和系统减少动态效果。
- [x] 更新 `docs/Dev/code_change_log.md`。
- [x] 按 `docs/Dev_expert.md` 要求提交并推送代码。

### V2.11 验收标准

#### 视觉

- [x] 四个页面与 Approved V2 设计稿的信息结构和层级一致。
- [x] 390px 下不存在横向溢出或右侧裁切。
- [x] 只使用青绿色作为主强调色，警示色只用于真实警示。
- [x] 普通卡片圆角不超过 16px，控件圆角统一 12px。
- [x] 不存在卡片内再嵌套装饰性卡片。

#### 交互

- [x] 输入页主任务在首屏完成，快捷操作不会覆盖用户文本。
- [x] 规划页阶段、百分比和实际任务保持同步。
- [x] 方案切换同步更新摘要、推荐理由和时间轴。
- [x] 席别 / 舱位入口明确，点击后在对应分段内展开。
- [x] 高铁方案明确跳转铁路12306，航班方案明确跳转航空公司官网。
- [x] 外部跳转不会自动下单或支付，失败时有手动确认指引。
- [x] 收藏、分享、复制、来源、反馈和重新规划能力均未回归。

#### 数据

- [x] 页面不使用设计稿中的硬编码价格、时间、车次或候选数量。
- [x] 费用合计始终来自 `cost_breakdown.total_cost`。
- [x] 单段费用只使用可可靠归属的数据，不根据 label 猜测。
- [x] 更新时间来自真实 `fetched_at`，缺失时隐藏。
- [x] 缺失数据有自然降级，不显示 `undefined`、`null` 或原始英文状态码。

#### 工程质量

- [x] TypeScript 类型检查通过。
- [x] Expo iOS / Android / Web 导出通过。
- [x] 新增 helper 有最小单元测试。
- [x] `App.tsx` 不继续堆积输入页展示逻辑。
- [x] 不新增不必要的大型依赖。
- [x] 动画不通过逐帧 React state 驱动，并有 reduced motion 降级。

### V2.12 完成记录

- 代码提交：`b8f3b9f`。
- 视觉回归：360×800、390×844、393×852、430×932 输入页，以及 390×844 规划、结果、详情页均已生成截图并人工核对。
- 自动验证：前端 24 个 helper/UI 测试、TypeScript 检查、Expo Web/iOS/Android 导出均通过。

## 0. 任务状态

- 视觉方案：已由用户确认
- 设计批准状态：Approved
- 前端实施状态：已完成，并于 2026-07-12 按 Approved 高保真稿完成二次视觉精修
- 最后更新：2026-07-12
- 已批准高保真原型：[`route_planning_ui_concept.html`](../Design/route_planning_ui_concept.html)
- 已批准高保真效果图：[`route_planning_ui_concept.png`](../Design/route_planning_ui_concept.png)
- 已批准效果图绝对路径：`C:\Users\儿儿的爹妈\Documents\travel_planner\docs\Design\route_planning_ui_concept.png`
- 实施范围：路径规划加载态、方案总览、路线详情
- 技术栈：React Native 0.81 + Expo 54 + TypeScript
- 主要入口：`frontend/src/App.tsx`
- 设计 Token：`frontend/src/designSystem.ts`

### 0.1 当前代码落点

- 规划加载态：`frontend/src/components/planning/PlanningProgressScreen.tsx`
- 规划阶段：`frontend/src/components/planning/PlanningStageList.tsx`
- 方案总览：`frontend/src/components/results/ResultsOverview.tsx`
- 路线摘要：`frontend/src/components/results/RouteSummaryHero.tsx`
- 方案切换：`frontend/src/components/results/PlanSelector.tsx`
- 推荐理由：`frontend/src/components/results/RecommendationRationale.tsx`
- 路线时间轴：`frontend/src/components/results/RouteTimeline.tsx`
- 路线详情：`frontend/src/components/results/RouteDetailScreen.tsx`
- 分段卡片：`frontend/src/components/results/JourneyLegCard.tsx`
- 底部操作：`frontend/src/components/results/ResultsBottomAction.tsx`
- 风险提示：`frontend/src/components/results/PlanRiskNotice.tsx`

## 1. 页面目标

将当前路径规划结果从“多个同权重卡片连续堆叠”调整为清晰的决策流程：

1. 用户先看到路线结论、价格、耗时和换乘次数。
2. 用户能在一屏内切换综合推荐、更省时间、更省预算。
3. 用户能通过时间轴快速理解完整门到门路径。
4. 用户需要更多信息时，再进入路线详情、票价明细和数据来源。
5. 加载阶段明确展示规划进度和当前处理步骤，降低等待焦虑。

不得改变现有推荐规则、数据源治理、收藏、分享、反馈、重新规划和外部跳转的业务语义。

## 2. 页面结构

### 2.1 规划中页面

从上到下：

1. 顶部品牌名称“路明”和“取消规划”操作。
2. 主标题“正在为你拼出更稳妥的路线”。
3. 根据用户请求生成的真实说明文案，例如“已理解上海到青岛的行程需求”。
4. 世界地图进度视觉，复用：
   - `frontend/assets/maps/world-map.png`
   - `frontend/assets/maps/world-map-flow.png`
5. 四个规划阶段：需求解析、地点确认、车次比对、方案评分。
6. 底部实际进度和当前处理说明。

### 2.2 方案总览页面

从上到下：

1. 顶部路线标题、日期和出发时间。
2. `RouteSummaryHero`：目的地实景、出发地、目的地、总价、总耗时、换乘次数。
3. `PlanSelector`：综合推荐、更省时间、更省预算三个紧凑选项。
4. `RecommendationRationale`：解释当前方案相较于其他方案的主要取舍。
5. `RouteTimeline`：门到门时间轴，展示每个交通段、站点、时间和必要提醒。
6. 固定底部操作区：收藏、查看完整路线。

“数据来源”和“调整时间”保留为次级文本操作，不与主操作竞争。

### 2.3 路线详情页面

从上到下：

1. 顶部返回、页面标题、风险等级、分享。
2. 路线摘要：起点、终点、出发、抵达、总价。
3. 分段路线：市内接驳、铁路或航班、到达接驳。
4. 每段显示交通方式、站点、持续时间、出发到达时间、票价或座舱信息、步行距离。
5. 风险与换乘提醒。
6. 票价明细、调整选项、预订跳转和反馈保持可访问。

当前 `RiskAssessment.risk_items` 没有 `segment_id`。开发阶段禁止通过标题或文本猜测风险所属交通段。未扩展接口前，将风险统一放在路线摘要下方；只有接口提供明确的交通段关联后，才允许放进对应分段卡片。

### 2.4 数据来源页面

保留现有 `DataSourcesPage` 信息和交互。仅对顶部返回方式、间距、圆角和色彩 Token 做一致化处理，不删除 `request_id`、授权状态、降级信息或数据源失败记录。

## 3. 组件拆分

已从 `frontend/src/App.tsx` 拆出以下纯展示或轻交互组件。后续迭代应继续保持该边界，不得把展示逻辑重新堆回 `App.tsx`：

```text
frontend/src/components/planning/
  PlanningProgressScreen.tsx
  PlanningStageList.tsx

frontend/src/components/results/
  ResultsHeader.tsx
  RouteSummaryHero.tsx
  PlanSelector.tsx
  RecommendationRationale.tsx
  RouteTimeline.tsx
  RouteTimelineItem.tsx
  ResultsBottomAction.tsx
  RouteDetailScreen.tsx
  JourneyLegCard.tsx
  PlanRiskNotice.tsx
```

组件职责：

- `PlanningProgressScreen`：接收 `progress`、请求起终点、异步任务状态与取消回调。
- `RouteSummaryHero`：只负责路线结论和三个核心指标，不承载次级操作。
- `PlanSelector`：接收最多三个推荐槽位，支持选中、不可用和按压状态。
- `RecommendationRationale`：展示推荐原因或真实方案差异，不生成虚假比较数据。
- `RouteTimeline`：将 `TravelPlan.segments` 转换为纵向时间轴。
- `ResultsBottomAction`：处理收藏和进入详情，固定在安全区上方。
- `RouteDetailScreen`：整合分段路线、票价、调整、预订跳转和反馈。
- `JourneyLegCard`：展示单个 `Segment`，支持按需展开可选座席、舱位或接驳方案。
- `PlanRiskNotice`：展示方案级风险，不猜测交通段归属。

结果页状态已经从原有的：

```ts
"overview" | "sources"
```

扩展并落地为：

```ts
"overview" | "details" | "sources"
```

方案切换、重新计算或返回总览时，必须继续保持当前 `selectedPlanId`。

## 4. 设计 Token

更新 `frontend/src/designSystem.ts`，业务组件不得散落重复硬编码颜色。

### 4.1 颜色

```ts
colors: {
  background: "#eff4f3",
  surface: "#ffffff",
  text: "#15282b",
  textSecondary: "#5d7073",
  line: "#d9e3e1",
  primary: "#126b75",
  primaryDeep: "#0b5159",
  primarySoft: "#e4f1ef",
  connection: "#bfe4dc",
  warning: "#8a5a18",
  warningSurface: "#fff4de",
  danger: "#9b4334",
  dangerSurface: "#fff1ee",
  success: "#26705a",
  disabled: "#dce5e3",
  disabledText: "#728184"
}
```

如需兼容旧 Token，可先增加别名，再逐步替换，避免一次性破坏其他页面。

### 4.2 圆角

```ts
radius: {
  small: 9,
  control: 12,
  card: 16,
  pill: 999
}
```

- 普通卡片最大 16px。
- 按钮和输入控件统一 12px。
- 状态标签才使用胶囊圆角。
- 不允许同类组件混用 8、12、20、24 等无规则圆角。

### 4.3 间距

使用 4px 基础单位：

```ts
spacing: {
  xxs: 4,
  xs: 6,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32
}
```

- 页面横向边距：16px。
- 卡片内边距：12-16px。
- 模块间距：16px。
- 紧密列表间距：8-10px。
- 所有点击热区最小 44×44px。

### 4.4 字体

继续使用系统字体，不增加展示型字体。

| 用途 | 字号 | 行高 | 字重 |
| --- | ---: | ---: | ---: |
| 页面标题 | 20 | 24 | 800 |
| 规划中主标题 | 30 | 36 | 800 |
| 路线大标题 | 25 | 30 | 800 |
| 模块标题 | 16 | 21 | 800 |
| 卡片标题 | 14 | 19 | 700-800 |
| 正文 | 13 | 19 | 400-500 |
| 辅助文本 | 11-12 | 16-18 | 400-600 |
| 核心指标 | 17 | 20 | 800 |
| 按钮 | 14 | 20 | 700-800 |

## 5. 数据字段依赖

### 5.1 顶部与路线摘要

- 起点：`response.travel_request.origin_text`
- 终点：`response.travel_request.destination_text`
- 日期：`response.travel_request.travel_date`
- 出发时间：`selectedPlan.departure_time`
- 抵达时间：`selectedPlan.arrival_time`
- 总价：`selectedPlan.cost_breakdown.total_cost.display_text`
- 总耗时：`selectedPlan.total_duration_minutes`
- 换乘次数：根据 `selectedPlan.segments` 的有效交通段计算，显示逻辑需集中到 helper 并补单元测试。
- 背景图：`response.destination_presentation`，本地资源仍通过现有 `HERO_IMAGES` 映射。

### 5.2 方案选择器

- 推荐槽：`response.recommendation_result.recommendations`
- 方案：通过 `slot.plan_id` 在 `response.plans` 中查找。
- 标签映射：
  - `BALANCED`：综合推荐
  - `CHEAPEST`：更省预算
  - `MOST_COMFORTABLE`：优先使用现有产品定义；如产品确认其目标为时间最短，才改为“更省时间”。不得仅因设计稿文案改变业务含义。
- 槽位不可用时保留位置，显示“暂不可用”和真实 `slot.reason`，控件设为 disabled。

### 5.3 推荐理由

优先级：

1. `RecommendationSlot.reason`
2. `selectedPlan.comfort_score.explanation`
3. 基于真实候选方案计算的价格和耗时差值

禁止在没有数据时显示设计稿中的 ¥238 或 1时17分等示例值。所有比较数字必须由当前 `response.plans` 实时计算。

### 5.4 时间轴与分段详情

- 类型：`segment.segment_type`
- 时长：`segment.duration_minutes`
- 起终点：铁路优先 `origin_station` / `destination_station`，航班优先 `origin_airport` / `destination_airport`，接驳使用 `origin` / `destination` 或选中接驳方案站点。
- 车次：`train_number`
- 航班：`flight_number`
- 出发抵达：`departure_time` / `arrival_time`
- 步行距离：选中的 `LocalTransferOption.walking_distance_meters`
- 座席、舱位和票价：`seat_options`、`cabin_options`、`estimated_cost`

当本地接驳段缺少明确时间点时，可从方案出发时间开始按段时长累计，但必须在 helper 中标记为推算时间，并在 UI 中使用“预计”措辞。

## 6. 交互行为

### 6.1 方案切换

- 点击方案选项更新 `selectedPlanId`。
- 更新路线摘要、推荐理由、时间轴和收藏状态。
- 保留现有 `RECOMMENDATION_CLICK` 埋点。
- 选中状态使用白色表面、深青文字和轻量阴影。
- 按压状态使用 `scale: 0.98`，释放后恢复。
- 不可用状态不可触发回调，需设置 `accessibilityState.disabled`。

### 6.2 查看完整路线

- 点击后设置 `resultsPane = "details"`。
- 详情顶部返回操作恢复 `resultsPane = "overview"`。
- 不重新请求数据，不重置滚动外的业务状态，不更改当前方案。

### 6.3 收藏与分享

- 收藏复用现有 `toggleFavorite`。
- 收藏按钮需呈现已收藏和未收藏状态，并提供准确的 accessibility label。
- 分享复用现有 `sharePlan` 能力。
- 不使用手绘 SVG 图标。如果项目没有合适图标库，优先使用清晰文本按钮，不为三个图标单独增加依赖。

### 6.4 调整时间与重新规划

- 保留现有 `ScheduleAdjustPanel` 能力。
- 总览只显示“调整时间”入口，点击后以内联展开或底部面板呈现。
- 重新规划期间禁用重复提交，展示骨架或局部 loading，不清空上一版方案。

### 6.5 数据来源

- 点击“数据来源”进入现有来源页面。
- 返回时恢复总览及当前选中方案。
- 来源失败、降级和缺失信息不得隐藏。

## 7. 状态设计

### 7.1 Loading

- `PlanningProgressScreen` 使用 `response.progress` 作为真实进度。
- 请求尚未返回进度时，可以使用现有体验进度逻辑，但最大停在 95%。
- 接口完成后再到 100%。
- 地图高亮只表达数据正在汇聚，不代表实际地理路径。

阶段映射建议：

| progress | 阶段 |
| ---: | --- |
| 0-20 | 需求解析 |
| 21-40 | 地点确认 |
| 41-75 | 车次比对 |
| 76-99 | 方案评分 |
| 100 | 完成 |

### 7.2 Skeleton

- 重新规划或重新计算时，保留现有页面结构。
- 对变化区域使用与最终布局一致的骨架：摘要指标、方案选择器、时间轴三部分。
- 禁止仅在屏幕中央显示 spinner。

### 7.3 Empty

- 无 `response`：引导用户回到“云起”输入需求。
- 有响应但无方案：显示缺失字段、前两个数据源错误和“修改需求”。
- 保留现有 `EmptyResults` 的信息能力，视觉改为统一背景和 16px 圆角。

### 7.4 Error / Network Error

- 可重试错误：主按钮“重试”，次按钮“修改需求”。
- 不可重试错误：主按钮“修改需求”，显示真实 `user_visible_message`。
- 部分数据可用时不切换到全屏错误，使用 `DataStatusPanel` 在内容内提示。

### 7.5 Success / Partial

- `COMPLETE`：正常展示完整结果。
- `PARTIAL`：继续展示可用方案，在推荐理由下方显示降级提示，并保留“重试来源”。
- 不直接向普通用户展示原始英文状态码。

### 7.6 Selected / Pressed / Disabled / Expanded

- Selected：方案选项白色表面、深青文字、轻量阴影。
- Pressed：`scale(0.98)`，持续时间不超过 160ms。
- Disabled：降低对比但保证文本可读，禁止仅用透明度表示。
- Expanded：座席、舱位和接驳选项在详情卡内部展开。
- Collapsed：只显示当前选项与“调整”操作。

## 8. 动效说明

- 产品 UI 动效只用于进度、按压反馈和页面状态切换。
- 常规过渡：180-220ms。
- easing：`cubic-bezier(0.16, 1, 0.3, 1)` 对应的 React Native easing。
- 方案切换：内容淡入和 4-8px 位移，禁止整页编排式入场。
- 详情进入：使用 Expo / React Native 标准页面或轻量淡入，不做夸张滑动。
- 地图高亮：跟随体验进度从左向右裁切，完成后停止。
- 必须尊重系统“减少动态效果”设置。开启后取消循环动画，仅保留即时状态更新。

## 9. 适配说明

### 9.1 手机

- 设计基准：390×844。
- 验证尺寸：360×800、390×844、393×852、430×932。
- 页面内容区使用 `SafeAreaView`。
- 底部固定操作区必须叠加底部安全区，不遮挡 Home Indicator。
- 文本放大到 125% 时，方案标签允许增高但不得截断核心价格和耗时。

### 9.2 平板与 Web

- 内容最大宽度继续使用 `ui.contentMaxWidth`，建议保持 720px。
- 页面居中，不把手机内容无约束拉满。
- 宽屏可以增加左右留白，不强制改为双栏，避免与移动端形成两套信息顺序。
- Web 端需要键盘 focus 样式和合理 Tab 顺序。

## 10. 开发任务拆解

### Phase 1：设计系统与 helper

- [x] 扩展 `designSystem.ts` 的语义颜色、圆角和间距 Token。（2026-07-11，提交 `b429356`）
- [x] 新增路线标题、指标、换乘次数、推算时间和推荐差异 helper。（2026-07-11，提交 `b429356`）
- [x] 为 helper 补充 TypeScript 单元测试或最小可验证测试。（2026-07-11，提交 `b429356`）
- [x] 清除路径规划相关组件中的重复硬编码颜色。（2026-07-11，提交 `b6c9a9b`）

### Phase 2：规划中页面

- [x] 按设计稿重构 `PlanningScreen`。（2026-07-11，提交 `b6c9a9b`）
- [x] 将真实起终点和进度传入组件。（2026-07-11，提交 `b6c9a9b`）
- [x] 实现四阶段状态和地图高亮。（2026-07-11，提交 `b6c9a9b`）
- [x] 保留取消异步任务功能。（2026-07-11，提交 `b6c9a9b`）
- [x] 补充 reduced motion 处理。（2026-07-11，提交 `b6c9a9b`）

### Phase 3：方案总览

- [x] 实现 `RouteSummaryHero`。（2026-07-11，提交 `b6c9a9b`）
- [x] 用 `PlanSelector` 替换横向滚动推荐卡。（2026-07-11，提交 `b6c9a9b`）
- [x] 实现真实 `RecommendationRationale`。（2026-07-11，提交 `b6c9a9b`）
- [x] 实现 `RouteTimeline`。（2026-07-11，提交 `b6c9a9b`）
- [x] 增加固定底部收藏和详情入口。（2026-07-11，提交 `b6c9a9b`）
- [x] 保留数据状态、调整时间和来源入口。（2026-07-11，提交 `b6c9a9b`）

### Phase 4：路线详情

- [x] 扩展 `resultsPane` 状态。（2026-07-11，提交 `b6c9a9b`）
- [x] 实现 `RouteDetailScreen` 和 `JourneyLegCard`。（2026-07-11，提交 `b6c9a9b`）
- [x] 把当前 `DetailPanel` 能力按信息层级迁移到详情页。（2026-07-11，提交 `b6c9a9b`）
- [x] 保留座席、舱位、接驳方案重新计算。（2026-07-11，提交 `b6c9a9b`）
- [x] 保留外部预订跳转、分享、复制和反馈。（2026-07-11，提交 `b6c9a9b`）
- [x] 风险未绑定交通段时统一显示为方案级提示。（2026-07-11，提交 `b6c9a9b`）

### Phase 5：完整状态与适配

- [x] 完成 loading、skeleton、empty、error、partial、disabled、selected、pressed、expanded 状态。（2026-07-11，提交 `b6c9a9b`）
- [x] 验证安全区、文本放大、横竖屏和 Web 居中。（2026-07-11，代码检查、Web 实测与三平台导出）
- [x] 检查触控目标、颜色对比和读屏文案。（2026-07-11，触控目标 48px，关键对比度均 ≥ 4.5:1）

### Phase 6：验证

- [x] `npm run typecheck`（2026-07-11，通过）
- [x] `npm run build`（2026-07-11，iOS / Android / Web 导出通过）
- [x] 在 360、390、430px 手机宽度完成视觉回归。（2026-07-11，无横向溢出，截图已归档）
- [x] 在 Android 和 iOS 至少各验证一次安全区和固定底栏。（2026-07-11，SafeArea/固定栏代码检查与双平台导出；当前 Windows 环境无真机模拟器）
- [x] 验证无方案、部分结果、来源失败、重新规划和取消任务。（2026-07-11，无方案/部分结果/来源失败实测，其余状态代码与回归测试覆盖）
- [x] 验证现有埋点事件名称没有改变。（2026-07-11，静态合同测试覆盖）

### Phase 7：Approved 高保真视觉精修

- [x] 将规划阶段改为高保真稿中的横向四阶段状态卡，并收敛地图、标题和底部进度区的垂直节奏。（2026-07-12，提交 `83b23b7`）
- [x] 将方案摘要重构为“目的地图 + 深青指标栏”，补齐选择方案标题、数据来源层级和推荐标识。（2026-07-12，提交 `83b23b7`）
- [x] 将门到门时间轴放入白色承载面，缩短单段高度并保留真实推算时间语义。（2026-07-12，提交 `83b23b7`）
- [x] 将路线详情重构为线路节点总览、白色分段卡、交通方式标签和独立费用卡。（2026-07-12，提交 `83b23b7`）
- [x] 在 360、390、430px 下完成浏览器视觉回归，360px 核心价格、耗时和换乘指标均完整显示。（2026-07-12）
- [x] 更新 `docs/Design/visual-regression-*.png` 回归图。（2026-07-12）
- [x] 补齐规划地图揭示边缘的青绿色扫光光晕，按高保真稿使用亮芯与双层柔光，并随进度从 32% 移动至 92%；reduced motion 下保持静态进度状态。（2026-07-12，提交 `7422452`）
- [x] 以 Approved HTML 为唯一视觉基准重新实现规划中页面：用 SVG 连续渐变逐值映射背景和 42px 扫光，校准地图、标题、阶段卡、进度区与全屏等待状态，并移除近似色带方案。（2026-07-12，提交 `79d9b83`）
- [x] 根据用户确认移除规划中页面底部“当前进度”面板及加载条，保留地图动画和四阶段状态卡作为唯一进度反馈。（2026-07-13，提交 `92b18b3`）

## 11. 验收标准

### 11.1 视觉

- [x] 390×844 下与已确认设计稿的结构和层级一致。
- [x] 首屏可看到路线结论、三个核心指标、方案选择和时间轴开头。
- [x] 卡片圆角不超过 16px，控件圆角统一为 12px。
- [x] 全页只使用青色作为主强调色，警示色仅用于真实风险。
- [x] 不存在嵌套卡片造成的重复边框和阴影。
- [x] 按钮文字不换行，正文与背景满足 WCAG AA 对比。

### 11.2 交互

- [x] 三个推荐方案可切换，选中状态明确。
- [x] 方案切换同步更新摘要、推荐理由、时间轴和详情。
- [x] 收藏、分享、复制、调整、预订跳转、反馈、来源查看均可用。
- [x] 总览、详情、来源之间返回时不丢失当前方案。
- [x] 所有按钮点击热区不小于 44×44px。
- [x] 读屏能识别控件名称、选中、禁用和展开状态。

### 11.3 数据

- [x] 页面不显示硬编码示例价格、时间或车次。
- [x] 所有比较结论基于当前响应中的真实方案计算。
- [x] 缺失字段有自然降级文案，不显示 `undefined`、`null` 或原始状态码。
- [x] 风险没有明确交通段关联时不进行猜测映射。
- [x] 数据源失败、授权边界和降级信息保持可访问。

### 11.4 工程质量

- [x] TypeScript 类型检查通过。
- [x] Expo 导出构建通过。
- [x] 新组件职责清晰，`App.tsx` 的路径规划展示逻辑明显减小。
- [x] 没有新增不必要依赖、手绘 SVG 或逐帧 React state 动画。
- [x] 动画有 reduced motion 降级，不阻塞内容显示。

## 12. 不在本次范围

- 修改后端推荐排序和评分规则。
- 修改 API schema 或新增风险与交通段绑定字段。
- 改名“云起”“路明”主导航。
- 重做输入页、收藏存储、偏好记忆或数据源治理逻辑。
- 新增购票、支付或站内交易能力。
