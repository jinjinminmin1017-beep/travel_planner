import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRouteTimeline,
  buildRouteTitle,
  applyRelaxationToRequest,
  calculatePlanDifference,
  countTransfers,
  findRecommendationReason,
  moneyDelta
} from "../src/utils/routePlanning.ts";

const source = {
  source_id: "test",
  source_name: "Test",
  source_type: "STATIC",
  authority_level: "TEST",
  license_status: "TEST_ONLY",
  commercial_allowed: false,
  fetched_at: { datetime: "2026-07-11T00:00:00+08:00", timezone: "Asia/Shanghai", source_timezone: "Asia/Shanghai" },
  cacheable: false
};

const money = (amount_minor) => ({ amount_minor, currency: "CNY", scale: 2, display_text: null });
const segment = (overrides) => ({
  segment_id: "segment",
  segment_type: "LOCAL_TRANSFER",
  origin: "家",
  destination: "车站",
  duration_minutes: 30,
  data_source: source,
  ...overrides
});
const plan = (overrides = {}) => ({
  schema_version: "1.17",
  plan_id: "plan-a",
  plan_name: "方案 A",
  plan_type: "DIRECT_RAIL",
  plan_lifecycle_status: "AVAILABLE",
  recommendation_eligibility: "ELIGIBLE",
  can_be_selected_by_llm: true,
  block_reason_code: null,
  block_reason_message: null,
  segments: [],
  total_duration_minutes: 180,
  departure_time: { datetime: "2026-07-11T08:00:00+08:00", timezone: "Asia/Shanghai", source_timezone: "Asia/Shanghai" },
  arrival_time: null,
  cost_breakdown: { total_cost: money(30000), items: [] },
  comfort_score: { total_score: 80, breakdown: {}, score_vector: { cost: 1, duration: 1, comfort: 1, risk: 1 }, confidence: 1, score_version: "test", explanation: "换乘较少" },
  risk_assessment: { overall_risk_level: "LOW", recommendation_allowed: true, risk_items: [] },
  data_quality: { completeness_score: 1, missing_components: [], warnings: [] },
  data_sources: [source],
  booking_redirects: [],
  ...overrides
});

test("buildRouteTitle degrades without undefined text", () => {
  assert.equal(buildRouteTitle({ origin_text: "上海", destination_text: "青岛" }), "上海 → 青岛");
  assert.equal(buildRouteTitle({ origin_text: "", destination_text: "" }), "路线待确认");
});

test("countTransfers counts transitions between valid door-to-door segments", () => {
  const segments = [
    segment({ segment_id: "local-a" }),
    segment({ segment_id: "rail", segment_type: "RAIL", origin_station: "上海虹桥", destination_station: "青岛北", duration_minutes: 300 }),
    segment({ segment_id: "local-b", origin: "青岛北", destination: "酒店" })
  ];
  assert.equal(countTransfers(segments), 2);
});

test("buildRouteTimeline marks only inferred times as estimated", () => {
  const timeline = buildRouteTimeline(plan({ segments: [segment({ segment_id: "local-a" }), segment({ segment_id: "local-b", origin: "车站", destination: "酒店", duration_minutes: 20 })] }));
  assert.equal(timeline[0].departureIsEstimated, true);
  assert.equal(timeline[0].arrivalIsEstimated, true);
  assert.equal(timeline[1].departureTime.datetime, "2026-07-11T00:30:00.000Z");
});

test("recommendation reason and comparison use response facts", () => {
  const selected = plan();
  const cheaper = plan({ plan_id: "plan-b", total_duration_minutes: 240, cost_breakdown: { total_cost: money(25000), items: [] } });
  assert.equal(findRecommendationReason(selected, [{ schema_version: "1.17", recommendation_type: "BALANCED", status: "AVAILABLE", plan_id: "plan-a", reason: "价格与时间更均衡" }]), "价格与时间更均衡");
  assert.deepEqual(calculatePlanDifference(selected, cheaper), { comparedPlanId: "plan-b", costDeltaMinor: 5000, durationDeltaMinutes: -60 });
  assert.equal(moneyDelta(selected.cost_breakdown.total_cost, 5000).display_text, "¥50.00");
});

test("confirmed relaxation updates the structured request before replanning", () => {
  const requested = { datetime: "2026-07-11T18:00:00+08:00", timezone: "Asia/Shanghai", source_timezone: "Asia/Shanghai" };
  const actual = { datetime: "2026-07-11T19:12:00+08:00", timezone: "Asia/Shanghai", source_timezone: "Asia/Shanghai" };
  const request = {
    schema_version: "1.17",
    request_id: "req-a",
    raw_user_input: "18点前到达",
    origin_text: "温州",
    destination_text: "武汉",
    travel_date: "2026-07-11",
    preferences: ["BALANCED"],
    preference_source: "USER_EXPLICIT",
    hard_constraints: { latest_arrival_time: requested, allowed_transport_modes: ["RAIL"], excluded_transport_modes: [] },
    soft_preferences: {}
  };
  const alternative = {
    alternative_id: "alt-a",
    category: "CLOSEST_TO_TIME",
    plan: plan(),
    preserved_constraints: ["ALLOWED_TRANSPORT_MODES"],
    user_confirmation_required: true,
    violations: [{ constraint_type: "LATEST_ARRIVAL", relaxation_policy: "USER_CONFIRMATION_REQUIRED", requested_value: requested, actual_value: actual, deviation: { kind: "DURATION", value: 72, unit: "MINUTE", direction: "LATER" }, reason_code: "TIME_CONSTRAINT_TOO_LATE", user_visible_message: "晚72分钟" }]
  };
  const relaxed = applyRelaxationToRequest(request, alternative);
  assert.equal(relaxed.hard_constraints.latest_arrival_time.datetime, actual.datetime);
  assert.equal(relaxed.schema_version, "1.17");
});
