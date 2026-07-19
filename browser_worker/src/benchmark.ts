import { randomUUID } from "node:crypto";

import { isRecord } from "./contracts.js";

interface BenchmarkCase {
  origin_iata: string;
  destination_iata: string;
  departure_date: string;
  adults?: number;
  currency_code?: string;
  max_results?: number;
}

interface BenchmarkObservation {
  success: boolean;
  total_ms: number;
  flight_count: number;
  cache_hit: boolean;
  error_code?: string;
}

const workerUrl = loopbackUrl(process.env.BROWSER_WORKER_BENCHMARK_URL?.trim() || "http://127.0.0.1:4319");
const requestCount = integerEnv("BROWSER_WORKER_BENCHMARK_REQUESTS", 50, 1, 500);
const intervalMs = integerEnv("BROWSER_WORKER_BENCHMARK_INTERVAL_MS", 10_000, 5_000, 60_000);
const cases = parseCases(process.env.BROWSER_WORKER_BENCHMARK_CASES ?? "");
if (cases.length < requestCount) {
  throw new Error(`BROWSER_WORKER_BENCHMARK_CASES must contain at least ${requestCount} distinct cases`);
}

const observations: BenchmarkObservation[] = [];
let consecutiveFailures = 0;
let abortedEarly = false;
for (const [index, benchmarkCase] of cases.slice(0, requestCount).entries()) {
  const started = performance.now();
  let observation: BenchmarkObservation;
  try {
    const response = await fetch(new URL("/v1/flight-search", workerUrl), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        request_id: `mubench_${randomUUID().replaceAll("-", "").slice(0, 16)}`,
        source_id: "airline_mu_browser_query",
        origin_iata: benchmarkCase.origin_iata,
        destination_iata: benchmarkCase.destination_iata,
        departure_date: benchmarkCase.departure_date,
        adults: benchmarkCase.adults ?? 1,
        currency_code: benchmarkCase.currency_code ?? "CNY",
        max_results: benchmarkCase.max_results ?? 20,
      }),
      signal: AbortSignal.timeout(60_000),
    });
    const payload: unknown = await response.json();
    observation = observationFromPayload(payload, Math.round(performance.now() - started));
  } catch {
    observation = {
      success: false,
      total_ms: Math.round(performance.now() - started),
      flight_count: 0,
      cache_hit: false,
      error_code: "BENCHMARK_REQUEST_FAILED",
    };
  }
  observations.push(observation);
  consecutiveFailures = observation.success ? 0 : consecutiveFailures + 1;
  process.stdout.write(
    `${JSON.stringify({
      iteration: index + 1,
      route: `${benchmarkCase.origin_iata}-${benchmarkCase.destination_iata}`,
      departure_date: benchmarkCase.departure_date,
      ...observation,
    })}\n`,
  );
  if (observation.error_code === "CIRCUIT_OPEN" || consecutiveFailures >= 3) {
    abortedEarly = true;
    break;
  }
  if (index + 1 < requestCount) await new Promise((resolve) => setTimeout(resolve, intervalMs));
}

const successful = observations.filter((item) => item.success);
const timings = successful.map((item) => item.total_ms).sort((left, right) => left - right);
const summary = {
  requests: observations.length,
  requested: requestCount,
  aborted_early: abortedEarly,
  successes: successful.length,
  success_rate: observations.length === 0 ? 0 : successful.length / observations.length,
  non_empty_results: successful.filter((item) => item.flight_count > 0).length,
  cache_hits: observations.filter((item) => item.cache_hit).length,
  challenges: observations.filter((item) => item.error_code?.startsWith("AIRLINE_")).length,
  p50_ms: percentile(timings, 0.5),
  p95_ms: percentile(timings, 0.95),
  p99_ms: percentile(timings, 0.99),
};
process.stdout.write(`${JSON.stringify({ summary })}\n`);
if (
  summary.requests !== summary.requested ||
  summary.success_rate < 0.95 ||
  summary.non_empty_results !== summary.successes ||
  summary.cache_hits > 0 ||
  summary.p50_ms > 8_000 ||
  summary.p95_ms > 15_000
) {
  process.exitCode = 1;
}

function parseCases(value: string): BenchmarkCase[] {
  if (!value.trim()) throw new Error("BROWSER_WORKER_BENCHMARK_CASES is required");
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) throw new Error("BROWSER_WORKER_BENCHMARK_CASES must be a JSON array");
  const result: BenchmarkCase[] = [];
  const seen = new Set<string>();
  for (const item of parsed) {
    if (!isRecord(item)) throw new Error("benchmark case must be an object");
    const benchmarkCase: BenchmarkCase = {
      origin_iata: validatedIata(item.origin_iata),
      destination_iata: validatedIata(item.destination_iata),
      departure_date: validatedDate(item.departure_date),
      ...(item.adults === undefined ? {} : { adults: validatedInteger(item.adults, 1, 9) }),
      ...(item.currency_code === undefined ? {} : { currency_code: validatedIata(item.currency_code) }),
      ...(item.max_results === undefined ? {} : { max_results: validatedInteger(item.max_results, 1, 20) }),
    };
    if (benchmarkCase.origin_iata === benchmarkCase.destination_iata) throw new Error("benchmark airports must differ");
    const key = JSON.stringify(benchmarkCase);
    if (seen.has(key)) throw new Error("benchmark cases must be distinct to prevent cache hits");
    seen.add(key);
    result.push(benchmarkCase);
  }
  return result;
}

function observationFromPayload(payload: unknown, fallbackMs: number): BenchmarkObservation {
  if (!isRecord(payload) || typeof payload.success !== "boolean") {
    return { success: false, total_ms: fallbackMs, flight_count: 0, cache_hit: false, error_code: "INVALID_WORKER_RESPONSE" };
  }
  const totalMs = Number.isInteger(payload.total_ms) && (payload.total_ms as number) >= 0 ? (payload.total_ms as number) : fallbackMs;
  const flights = Array.isArray(payload.flights) ? payload.flights : [];
  return {
    success: payload.success,
    total_ms: totalMs,
    flight_count: flights.length,
    cache_hit: payload.cache_hit === true,
    ...(typeof payload.error_code === "string" ? { error_code: payload.error_code } : {}),
  };
}

function loopbackUrl(value: string): URL {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
    throw new Error("benchmark URL must use HTTP loopback");
  }
  return url;
}

function validatedIata(value: unknown): string {
  const text = String(value ?? "").trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(text)) throw new Error("benchmark IATA/currency value is invalid");
  return text;
}

function validatedDate(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || Number.isNaN(Date.parse(`${text}T00:00:00+08:00`))) {
    throw new Error("benchmark date is invalid");
  }
  return text;
}

function validatedInteger(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new Error("benchmark integer is invalid");
  }
  return value as number;
}

function integerEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : fallback;
}

function percentile(values: number[], fraction: number): number {
  if (values.length === 0) return 0;
  return values[Math.max(0, Math.ceil(values.length * fraction) - 1)] ?? 0;
}
