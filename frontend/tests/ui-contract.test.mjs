import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("results flow keeps overview, details and sources panes", async () => {
  const app = await read("../src/App.tsx");
  assert.match(app, /type ResultsPane = "overview" \| "details" \| "sources"/);
  assert.match(app, /<ResultsOverview/);
  assert.match(app, /<RouteDetailScreen/);
  assert.match(app, /<ResultsBottomAction/);
});

test("results keep transport modes separate from recommendation targets", async () => {
  const app = await read("../src/App.tsx");
  const overview = await read("../src/components/results/ResultsOverview.tsx");
  const transportModes = await read("../src/components/results/TransportModeSelector.tsx");
  assert.match(overview, /<TransportModeSelector/);
  assert.match(overview, />推荐目标</);
  assert.match(transportModes, /const MODES: IntercityTransportMode\[\] = \["RAIL", "FLIGHT"\]/);
  assert.match(transportModes, /不会生成占位航班、价格或预订入口/);
  assert.match(app, /EXPO_PUBLIC_TRANSPORT_MODE_SELECTOR_ENABLED/);
  assert.doesNotMatch(transportModes, /plan_id|flight_number|amount_minor/);
});

test("route UI does not contain design-only example values", async () => {
  const sources = await Promise.all([
    read("../src/components/results/RouteSummaryHero.tsx"),
    read("../src/components/results/RecommendationRationale.tsx"),
    read("../src/components/results/RouteTimeline.tsx"),
    read("../src/components/results/RouteDetailScreen.tsx")
  ]);
  const combined = sources.join("\n");
  assert.doesNotMatch(combined, /¥238|1时17分|G1234|MU1234/);
});

test("existing analytics event names remain wired after component extraction", async () => {
  const combined = `${await read("../src/App.tsx")}\n${await read("../src/components/results/RouteDetailScreen.tsx")}`;
  for (const eventName of ["INPUT_SUBMITTED", "PLANNING_SUCCESS", "PLANNING_PARTIAL", "PLANNING_NO_MATCH", "RECOMMENDATION_CLICK", "REDIRECT_CLICK", "FEEDBACK_SUBMITTED", "RECENT_PLAN_VIEWED", "FAVORITE_TOGGLED", "PREFERENCE_UPDATED"]) {
    assert.match(combined, new RegExp(`"${eventName}"`));
  }
});

test("approved V2 removes the plan risk card and embeds route costs", async () => {
  const detail = await read("../src/components/results/RouteDetailScreen.tsx");
  assert.doesNotMatch(detail, /PlanRiskNotice|riskLabel/);
  assert.match(detail, /<JourneyCostSummary presentation=\{costPresentation\}/);
  assert.match(detail, /buildOfficialRedirectPresentation\(plan\)/);
  assert.match(detail, /redirectPresentation\.buttonLabel/);
});

test("approved V2 extracts the input flow and keeps retention actions", async () => {
  const app = await read("../src/App.tsx");
  const input = await read("../src/components/input/TravelInputScreen.tsx");
  assert.match(app, /<TravelInputScreen/);
  assert.match(input, /今天，想去哪里？/);
  assert.match(input, /明天出发/);
  assert.match(input, /少换乘/);
  assert.match(input, /脱敏摘要/);
  assert.match(input, /收藏方案/);
  assert.match(input, /出行偏好/);
});

test("rail seat recalculation replaces the full result set while transfers stay plan-scoped", async () => {
  const detail = await read("../src/components/results/RouteDetailScreen.tsx");
  const app = await read("../src/App.tsx");
  const client = await read("../src/api/client.ts");
  assert.match(detail, /changeType === "SEAT_TYPE" \? "RESULT_SET" : "TARGET_PLAN"/);
  assert.match(detail, /changeType === "SEAT_TYPE" \? "FULL_REEVALUATION"/);
  assert.match(client, /application_scope: applicationScope/);
  assert.match(app, /if \(updatedResponse\.updated_response\)/);
  assert.match(app, /setResponse\(completeResponse\)/);
});

test("planning map keeps the approved progress glow aligned to the reveal edge", async () => {
  const planning = await read("../src/components/planning/PlanningProgressScreen.tsx");
  const app = await read("../src/App.tsx");
  const tokens = await read("../src/designSystem.ts");
  assert.match(planning, /styles\.glowSweep, \{ left: mapClipWidth \}/);
  assert.match(planning, /<SvgLinearGradient id="mapSweep"/);
  assert.match(planning, /offset="50%" stopColor=\{ui\.colors\.mapGlow\} stopOpacity=\{0\.22\}/);
  assert.match(planning, /outputRange: \["32%", "92%"\]/);
  assert.match(planning, /glowSweep: \{ bottom: 0, marginLeft: -21,[^\n]+width: 42 \}/);
  assert.match(planning, /duration: normalizedProgress >= 100 \? 220 : 5_000/);
  assert.match(tokens, /mapGlow: "#7ee9d4"/);
  assert.match(app, /!planningFullScreen \? <View style=\{styles\.bottomTabs\}>/);
  assert.match(app, /planningFullScreen && styles\.planningContent/);
  assert.doesNotMatch(planning, /glowOuter|glowMiddle|glowCore/);
  assert.match(planning, /stagePresentation\.currentTask/);
  assert.match(planning, /规划完成后会保留结果/);
});

test("no-match alternatives expose decision facts without a booking action", async () => {
  const noMatch = await read("../src/components/constraints/ConstraintNoMatchScreen.tsx");
  for (const label of ["门到门概览", "完整路线", "确认后将放宽的条件", "仍满足的条件", "数据与风险", "航司查询说明"]) {
    assert.match(noMatch, new RegExp(label));
  }
  assert.match(noMatch, /alternative\.plan\.segments\.map/);
  assert.match(noMatch, /alternative\.violations\.map/);
  assert.match(noMatch, /response\.source_failures/);
  assert.match(noMatch, /此处不提供购票入口/);
  assert.doesNotMatch(noMatch, /bookingRedirect|booking_redirect|onBooking|onBook/);
});
