# 路径规划前端落地任务

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
