import assert from "node:assert/strict";
import test from "node:test";

import {
  derivePlanningPageState,
  hasObservationWindowExpired,
  isPlanningActive,
  nextPollDelayMs
  , nextResponsePollDelayMs
} from "../src/planning/planningState.ts";

const snapshot = (planningStatus, jobStatus, planCount = 0) => ({
  planning_status: planningStatus,
  plans: Array.from({ length: planCount }, (_, index) => ({ plan_id: `plan-${index}` })),
  async_job: jobStatus ? { job_status: jobStatus } : null
});

test("active empty response never derives the terminal empty page", () => {
  const response = snapshot("RUNNING", "WAITING_SOURCE");
  assert.equal(isPlanningActive(response), true);
  assert.equal(derivePlanningPageState({
    response,
    observationState: "OBSERVING",
    errorType: "NON_BLOCKING"
  }), "PLANNING_EMPTY");
});

test("observation exhaustion is a local paused state instead of a business terminal", () => {
  assert.equal(derivePlanningPageState({
    response: snapshot("RUNNING", "RUNNING"),
    observationState: "PAUSED",
    errorType: "NONE"
  }), "OBSERVATION_PAUSED");
});

test("active results, no-match, failed, partial and complete are mutually exclusive", () => {
  assert.equal(derivePlanningPageState({
    response: snapshot("RUNNING", "RUNNING", 1),
    observationState: "OBSERVING",
    errorType: "NONE"
  }), "PLANNING_WITH_RESULTS");
  assert.equal(derivePlanningPageState({
    response: snapshot("NO_MATCH", "COMPLETE"),
    observationState: "IDLE",
    errorType: "NONE"
  }), "NO_MATCH");
  assert.equal(derivePlanningPageState({
    response: snapshot("FAILED", "FAILED"),
    observationState: "IDLE",
    errorType: "NONE"
  }), "FAILED");
  assert.equal(derivePlanningPageState({
    response: snapshot("PARTIAL", "PARTIAL_READY", 1),
    observationState: "IDLE",
    errorType: "NON_BLOCKING"
  }), "RESULTS");
  assert.equal(derivePlanningPageState({
    response: snapshot("COMPLETE", "COMPLETE", 1),
    observationState: "IDLE",
    errorType: "NONE"
  }), "RESULTS");
});

test("terminal results retain a non-blocking error panel", () => {
  assert.equal(derivePlanningPageState({
    response: snapshot("COMPLETE", "COMPLETE", 1),
    observationState: "IDLE",
    errorType: "NON_BLOCKING"
  }), "RESULTS");
});

test("elapsed observation timing and capped backoff are deterministic with a fake clock", () => {
  assert.equal(hasObservationWindowExpired(1_000, 120_999, 120_000), false);
  assert.equal(hasObservationWindowExpired(1_000, 121_000, 120_000), true);
  assert.equal(nextPollDelayMs(0, 0.5), 1_200);
  assert.equal(nextPollDelayMs(99, 0.5), 5_000);
});

test("active empty jobs poll within two seconds and relax after first plan", () => {
  assert.equal(nextResponsePollDelayMs(99, false, 1), 2_000);
  assert.equal(nextResponsePollDelayMs(99, false, 0), 2_000);
  assert.equal(nextResponsePollDelayMs(99, true, 0.5), 5_000);
  assert.ok(nextResponsePollDelayMs(0, false, 0.5) <= 2_000);
});
