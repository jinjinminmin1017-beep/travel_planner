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

test("plan risks stay at plan level without text-based segment matching", async () => {
  const detail = await read("../src/components/results/RouteDetailScreen.tsx");
  const riskNotice = await read("../src/components/results/PlanRiskNotice.tsx");
  assert.match(detail, /<PlanRiskNotice plan=\{plan\}/);
  assert.doesNotMatch(riskNotice, /segment_id|segmentTitle|includes\(/);
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
