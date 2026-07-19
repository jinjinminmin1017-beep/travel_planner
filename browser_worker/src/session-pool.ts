import type { FlightSearchInput, FlightSearchResponse } from "./contracts.js";
import { searchKey } from "./contracts.js";
import { stableError, WorkerSearchError } from "./errors.js";
import type { BrowserExecutionResult } from "./browser-manager.js";

interface BrowserExecutor {
  execute(input: FlightSearchInput, signal?: AbortSignal): Promise<BrowserExecutionResult>;
}

interface CacheEntry {
  expiresAt: number;
  response: FlightSearchResponse;
}

interface CircuitState {
  failures: number;
  openUntil: number;
}

export interface WorkerMetrics {
  searches: number;
  successes: number;
  empty_results: number;
  challenges: number;
  cache_hits: number;
  inflight_dedup_hits: number;
  timeouts: number;
  parse_errors: number;
  circuit_open: number;
}

interface MutableSourceMetrics extends WorkerMetrics {
  cold_ms: number[];
  warm_ms: number[];
  observed_queries: number;
}

export interface LatencySnapshot {
  samples: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface SourceMetricsSnapshot extends WorkerMetrics {
  success_rate: number;
  empty_result_rate: number;
  challenge_rate: number;
  latency: {
    cold: LatencySnapshot;
    warm: LatencySnapshot;
  };
}

export class SessionPool {
  private readonly queues = new Map<string, Promise<void>>();
  private readonly queueDepth = new Map<string, number>();
  private readonly inflight = new Map<string, Promise<FlightSearchResponse>>();
  private readonly cache = new Map<string, CacheEntry>();
  private readonly circuits = new Map<string, CircuitState>();
  private readonly sourceMetrics = new Map<string, MutableSourceMetrics>();
  readonly metrics: WorkerMetrics = {
    searches: 0,
    successes: 0,
    empty_results: 0,
    challenges: 0,
    cache_hits: 0,
    inflight_dedup_hits: 0,
    timeouts: 0,
    parse_errors: 0,
    circuit_open: 0,
  };

  constructor(
    private readonly manager: BrowserExecutor,
    private readonly cacheTtlMs = numberEnv("BROWSER_WORKER_CACHE_TTL_SECONDS", 90, 60, 180) * 1_000,
    private readonly totalTimeoutMs = numberEnv("BROWSER_WORKER_TOTAL_TIMEOUT_MS", 20_000, 2_000, 60_000),
  ) {}

  search(input: FlightSearchInput): Promise<FlightSearchResponse> {
    const key = searchKey(input);
    const cached = this.cache.get(key);
    if (cached && cached.expiresAt > Date.now()) {
      this.metrics.cache_hits += 1;
      this.sourceMetric(input.source_id).cache_hits += 1;
      return Promise.resolve(cachedHit(cached.response));
    }
    this.cache.delete(key);
    const existing = this.inflight.get(key);
    if (existing) {
      this.metrics.inflight_dedup_hits += 1;
      this.sourceMetric(input.source_id).inflight_dedup_hits += 1;
      return existing;
    }
    const enqueuedAt = performance.now();
    const task = this.enqueue(input.source_id, () => this.execute(input, enqueuedAt));
    this.inflight.set(key, task);
    void task.finally(() => this.inflight.delete(key));
    return task;
  }

  health(): {
    queue_depth: Record<string, number>;
    metrics: WorkerMetrics;
    source_metrics: Record<string, SourceMetricsSnapshot>;
  } {
    return {
      queue_depth: Object.fromEntries(this.queueDepth),
      metrics: { ...this.metrics },
      source_metrics: Object.fromEntries(
        [...this.sourceMetrics.entries()].map(([sourceId, metric]) => [sourceId, sourceSnapshot(metric)]),
      ),
    };
  }

  private enqueue(sourceId: string, operation: () => Promise<FlightSearchResponse>): Promise<FlightSearchResponse> {
    const previous = this.queues.get(sourceId) ?? Promise.resolve();
    this.queueDepth.set(sourceId, (this.queueDepth.get(sourceId) ?? 0) + 1);
    let release: () => void = () => undefined;
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.queues.set(sourceId, previous.then(() => current));
    return previous
      .then(operation)
      .finally(() => {
        release();
        const depth = Math.max(0, (this.queueDepth.get(sourceId) ?? 1) - 1);
        this.queueDepth.set(sourceId, depth);
        if (depth === 0) this.queues.delete(sourceId);
      });
  }

  private async execute(input: FlightSearchInput, enqueuedAt: number): Promise<FlightSearchResponse> {
    const started = performance.now();
    const queueMs = Math.max(0, Math.round(started - enqueuedAt));
    this.metrics.searches += 1;
    const sourceMetric = this.sourceMetric(input.source_id);
    sourceMetric.searches += 1;
    const isCold = sourceMetric.observed_queries === 0;
    const circuit = this.circuits.get(input.source_id);
    if (circuit && circuit.openUntil > Date.now()) {
      this.metrics.circuit_open += 1;
      sourceMetric.circuit_open += 1;
      return failure(input, started, queueMs, new WorkerSearchError("CIRCUIT_OPEN", "airline circuit is temporarily open", true));
    }
    try {
      const controller = new AbortController();
      const result = await withTimeout(
        this.manager.execute(input, controller.signal),
        this.totalTimeoutMs,
        () => controller.abort(),
      );
      const response: FlightSearchResponse = {
        success: true,
        source_id: input.source_id,
        flights: result.flights,
        evidence_id: result.evidence_id,
        cache_hit: false,
        queue_ms: queueMs,
        navigation_ms: result.navigation_ms,
        response_ms: result.response_ms,
        parse_ms: result.parse_ms,
        total_ms: Math.max(0, Math.round(performance.now() - started)),
      };
      this.circuits.delete(input.source_id);
      this.metrics.successes += 1;
      sourceMetric.successes += 1;
      if (response.flights.length === 0) {
        this.metrics.empty_results += 1;
        sourceMetric.empty_results += 1;
      }
      recordLatency(sourceMetric, isCold, response.total_ms);
      this.cache.set(searchKey(input), { expiresAt: Date.now() + this.cacheTtlMs, response });
      return response;
    } catch (error) {
      const stable = stableError(error);
      if (stable.challenge) {
        this.metrics.challenges += 1;
        sourceMetric.challenges += 1;
      }
      if (stable.code === "WORKER_TIMEOUT") {
        this.metrics.timeouts += 1;
        sourceMetric.timeouts += 1;
      }
      if (stable.code.includes("PARSE") || stable.code.includes("STRUCTURE")) {
        this.metrics.parse_errors += 1;
        sourceMetric.parse_errors += 1;
      }
      const nextFailures = (this.circuits.get(input.source_id)?.failures ?? 0) + 1;
      this.circuits.set(input.source_id, {
        failures: nextFailures,
        openUntil: nextFailures >= 3 ? Date.now() + 30_000 : 0,
      });
      const response = failure(input, started, queueMs, stable);
      recordLatency(sourceMetric, isCold, response.total_ms);
      return response;
    }
  }

  private sourceMetric(sourceId: string): MutableSourceMetrics {
    const existing = this.sourceMetrics.get(sourceId);
    if (existing) return existing;
    const created: MutableSourceMetrics = {
      searches: 0,
      successes: 0,
      empty_results: 0,
      challenges: 0,
      cache_hits: 0,
      inflight_dedup_hits: 0,
      timeouts: 0,
      parse_errors: 0,
      circuit_open: 0,
      cold_ms: [],
      warm_ms: [],
      observed_queries: 0,
    };
    this.sourceMetrics.set(sourceId, created);
    return created;
  }
}

function cachedHit(response: FlightSearchResponse): FlightSearchResponse {
  return response.success ? { ...response, cache_hit: true, total_ms: 0, queue_ms: 0 } : response;
}

function failure(
  input: FlightSearchInput,
  started: number,
  queueMs: number,
  error: WorkerSearchError,
): FlightSearchResponse {
  return {
    success: false,
    source_id: input.source_id,
    flights: [],
    error_code: error.code,
    message: error.message,
    retryable: error.retryable,
    ...(error.challenge ? { challenge: error.challenge } : {}),
    queue_ms: queueMs,
    navigation_ms: 0,
    response_ms: 0,
    parse_ms: 0,
    total_ms: Math.max(0, Math.round(performance.now() - started)),
  };
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, onTimeout: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => {
      onTimeout();
      reject(new WorkerSearchError("WORKER_TIMEOUT", "browser search timed out", true));
    }, timeoutMs);
    void promise.then(
      (value) => {
        clearTimeout(timeout);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

function numberEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}

function recordLatency(metric: MutableSourceMetrics, cold: boolean, value: number): void {
  const samples = cold ? metric.cold_ms : metric.warm_ms;
  samples.push(value);
  if (samples.length > 200) samples.shift();
  metric.observed_queries += 1;
}

function sourceSnapshot(metric: MutableSourceMetrics): SourceMetricsSnapshot {
  return {
    searches: metric.searches,
    successes: metric.successes,
    empty_results: metric.empty_results,
    challenges: metric.challenges,
    cache_hits: metric.cache_hits,
    inflight_dedup_hits: metric.inflight_dedup_hits,
    timeouts: metric.timeouts,
    parse_errors: metric.parse_errors,
    circuit_open: metric.circuit_open,
    success_rate: rate(metric.successes, metric.searches),
    empty_result_rate: rate(metric.empty_results, metric.successes),
    challenge_rate: rate(metric.challenges, metric.searches),
    latency: {
      cold: latencySnapshot(metric.cold_ms),
      warm: latencySnapshot(metric.warm_ms),
    },
  };
}

function rate(numerator: number, denominator: number): number {
  return denominator === 0 ? 0 : numerator / denominator;
}

function latencySnapshot(values: number[]): LatencySnapshot {
  const sorted = [...values].sort((left, right) => left - right);
  return {
    samples: sorted.length,
    p50_ms: percentile(sorted, 0.5),
    p95_ms: percentile(sorted, 0.95),
    p99_ms: percentile(sorted, 0.99),
  };
}

function percentile(values: number[], fraction: number): number {
  if (values.length === 0) return 0;
  return values[Math.max(0, Math.ceil(values.length * fraction) - 1)] ?? 0;
}
