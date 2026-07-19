import type { FlightSearchInput, FlightSearchResponse } from "./contracts.js";
import { searchKey } from "./contracts.js";
import { stableError, WorkerSearchError } from "./errors.js";
import type { BrowserExecutionResult } from "./browser-manager.js";

interface BrowserExecutor {
  execute(input: FlightSearchInput): Promise<BrowserExecutionResult>;
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

export class SessionPool {
  private readonly queues = new Map<string, Promise<void>>();
  private readonly queueDepth = new Map<string, number>();
  private readonly inflight = new Map<string, Promise<FlightSearchResponse>>();
  private readonly cache = new Map<string, CacheEntry>();
  private readonly circuits = new Map<string, CircuitState>();
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
  ) {}

  search(input: FlightSearchInput): Promise<FlightSearchResponse> {
    const key = searchKey(input);
    const cached = this.cache.get(key);
    if (cached && cached.expiresAt > Date.now()) {
      this.metrics.cache_hits += 1;
      return Promise.resolve(cachedHit(cached.response));
    }
    this.cache.delete(key);
    const existing = this.inflight.get(key);
    if (existing) {
      this.metrics.inflight_dedup_hits += 1;
      return existing;
    }
    const enqueuedAt = performance.now();
    const task = this.enqueue(input.source_id, () => this.execute(input, enqueuedAt));
    this.inflight.set(key, task);
    void task.finally(() => this.inflight.delete(key));
    return task;
  }

  health(): { queue_depth: Record<string, number>; metrics: WorkerMetrics } {
    return { queue_depth: Object.fromEntries(this.queueDepth), metrics: { ...this.metrics } };
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
    const circuit = this.circuits.get(input.source_id);
    if (circuit && circuit.openUntil > Date.now()) {
      this.metrics.circuit_open += 1;
      return failure(input, started, queueMs, new WorkerSearchError("CIRCUIT_OPEN", "airline circuit is temporarily open", true));
    }
    try {
      const result = await withTimeout(
        this.manager.execute(input),
        numberEnv("BROWSER_WORKER_TOTAL_TIMEOUT_MS", 20_000, 2_000, 60_000),
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
      if (response.flights.length === 0) this.metrics.empty_results += 1;
      this.cache.set(searchKey(input), { expiresAt: Date.now() + this.cacheTtlMs, response });
      return response;
    } catch (error) {
      const stable = stableError(error);
      if (stable.challenge) this.metrics.challenges += 1;
      if (stable.code === "WORKER_TIMEOUT") this.metrics.timeouts += 1;
      if (stable.code.includes("PARSE") || stable.code.includes("STRUCTURE")) this.metrics.parse_errors += 1;
      const nextFailures = (this.circuits.get(input.source_id)?.failures ?? 0) + 1;
      this.circuits.set(input.source_id, {
        failures: nextFailures,
        openUntil: nextFailures >= 3 ? Date.now() + 30_000 : 0,
      });
      return failure(input, started, queueMs, stable);
    }
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

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new WorkerSearchError("WORKER_TIMEOUT", "browser search timed out", true)), timeoutMs);
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
