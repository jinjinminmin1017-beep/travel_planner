import assert from "node:assert/strict";
import test from "node:test";

import type { BrowserExecutionResult } from "../src/browser-manager.js";
import type { FlightSearchInput } from "../src/contracts.js";
import { SessionPool } from "../src/session-pool.js";

const baseInput: FlightSearchInput = {
  request_id: "req-1",
  source_id: "airline_mu_browser_query",
  origin_iata: "PVG",
  destination_iata: "TAO",
  departure_date: "2026-07-23",
  adults: 1,
  currency_code: "CNY",
  max_results: 5,
};

test("identical in-flight searches are merged and successful results are cached", async () => {
  let calls = 0;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const manager = {
    async execute(): Promise<BrowserExecutionResult> {
      calls += 1;
      await gate;
      return result();
    },
  };
  const pool = new SessionPool(manager, 60_000);

  const first = pool.search(baseInput);
  const second = pool.search(baseInput);
  release?.();
  const [firstResult, secondResult] = await Promise.all([first, second]);
  const thirdResult = await pool.search(baseInput);

  assert.equal(calls, 1);
  assert.equal(firstResult.success, true);
  assert.deepEqual(secondResult, firstResult);
  assert.equal(thirdResult.success && thirdResult.cache_hit, true);
  assert.equal(pool.metrics.inflight_dedup_hits, 1);
  assert.equal(pool.metrics.cache_hits, 1);
});

test("different searches for the same airline execute serially", async () => {
  let active = 0;
  let maximumActive = 0;
  const manager = {
    async execute(): Promise<BrowserExecutionResult> {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      await new Promise((resolve) => setTimeout(resolve, 10));
      active -= 1;
      return result();
    },
  };
  const pool = new SessionPool(manager, 60_000);

  await Promise.all([
    pool.search(baseInput),
    pool.search({ ...baseInput, request_id: "req-2", departure_date: "2026-07-24" }),
  ]);

  assert.equal(maximumActive, 1);
});

function result(): BrowserExecutionResult {
  return {
    flights: [],
    evidence_id: "mubw_test",
    navigation_ms: 5,
    response_ms: 5,
    parse_ms: 1,
  };
}
