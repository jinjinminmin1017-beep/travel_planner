import { existsSync } from "node:fs";
import { isAbsolute } from "node:path";

import { chromium, type Browser, type BrowserContext, type LaunchOptions, type Page, type Response } from "playwright";

import type { BrowserFlightResult, ChallengeResult, FlightSearchInput } from "./contracts.js";
import { WorkerSearchError } from "./errors.js";
import type { AirlineBrowserHandler } from "./airlines/types.js";

interface AirlineSession {
  context: BrowserContext;
  page: Page;
}

export interface BrowserLifecycleMetrics {
  browser_restarts: number;
  context_rebuilds: number;
  page_rebuilds: number;
}

export interface BrowserExecutionResult extends BrowserFlightResult {
  navigation_ms: number;
  response_ms: number;
  parse_ms: number;
}

export class BrowserManager {
  private browser: Browser | null = null;
  private readonly sessions = new Map<string, AirlineSession>();
  private launchedOnce = false;
  readonly metrics: BrowserLifecycleMetrics = {
    browser_restarts: 0,
    context_rebuilds: 0,
    page_rebuilds: 0,
  };

  constructor(
    private readonly handlers: Map<string, AirlineBrowserHandler>,
    private readonly headless = process.env.BROWSER_WORKER_HEADLESS?.toLowerCase() !== "false",
    private readonly launchBrowser: (options: LaunchOptions) => Promise<Browser> = (options) => chromium.launch(options),
  ) {}

  async start(enabledSourceIds: string[]): Promise<void> {
    await this.ensureBrowser();
    for (const sourceId of enabledSourceIds) {
      const handler = this.handlers.get(sourceId);
      if (!handler) throw new WorkerSearchError("SOURCE_NOT_IMPLEMENTED", `${sourceId} is not implemented`, false);
      const session = await this.createSession(sourceId);
      await handler.warmUp(session.page);
    }
  }

  async execute(input: FlightSearchInput, signal?: AbortSignal): Promise<BrowserExecutionResult> {
    throwIfAborted(signal);
    const handler = this.handlers.get(input.source_id);
    if (!handler) throw new WorkerSearchError("SOURCE_NOT_IMPLEMENTED", `${input.source_id} is not implemented`, false);
    let session = await this.getSession(input.source_id);
    if (session.page.isClosed()) {
      await this.rebuildPage(input.source_id);
      session = await this.getSession(input.source_id);
    }
    const navigationStarted = performance.now();
    const targetResponse = session.page.waitForResponse(
      (response) => handler.matchesResponse(response, input),
      { timeout: numberEnv("BROWSER_WORKER_RESPONSE_TIMEOUT_MS", 15_000, 1_000, 60_000) },
    );
    let observedChallengeResponse: Response | undefined;
    const observeResponse = (response: Response): void => {
      if (handler.matchesChallengeResponse?.(response)) observedChallengeResponse = response;
    };
    const observingResponses = handler.matchesChallengeResponse !== undefined;
    if (observingResponses) session.page.on("response", observeResponse);
    const detachObserver = (): void => {
      if (observingResponses) session.page.off("response", observeResponse);
    };
    let navigationFinished = navigationStarted;
    try {
      await raceWithAbort(handler.triggerSearch(session.page, input), signal);
      navigationFinished = performance.now();
      type Completion = { kind: "response"; response: Response } | { kind: "page" };
      const completions: Array<Promise<Completion>> = [
        targetResponse.then((response) => ({ kind: "response" as const, response })),
      ];
      if (handler.waitForPageResult && handler.parsePage) {
        completions.push(handler.waitForPageResult(session.page, input).then(() => ({ kind: "page" as const })));
      }
      const completion = await raceWithAbort(Promise.race(completions), signal);
      const responseAt = performance.now();
      const response = completion.kind === "response" ? completion.response : undefined;
      if (!response) void targetResponse.catch(() => undefined);
      throwIfAborted(signal);
      const challenge = await handler.detectChallenge(session.page, response);
      if (challenge) throw challengeError(challenge);
      const parseStarted = performance.now();
      const result = await raceWithAbort(
        response
          ? handler.parseResponse(response, session.page, input)
          : handler.parsePage!(session.page, input),
        signal,
      );
      const finished = performance.now();
      detachObserver();
      return {
        ...result,
        navigation_ms: Math.max(0, Math.round(navigationFinished - navigationStarted)),
        response_ms: Math.max(0, Math.round(responseAt - navigationFinished)),
        parse_ms: Math.max(0, Math.round(finished - parseStarted)),
      };
    } catch (error) {
      void targetResponse.catch(() => undefined);
      detachObserver();
      if (isAbortError(error)) throw error;
      const challenge = await handler.detectChallenge(session.page, observedChallengeResponse).catch(() => null);
      if (challenge) throw challengeError(challenge);
      if (session.page.isClosed()) await this.rebuildPage(input.source_id).catch(() => undefined);
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.sessions.clear();
    await this.browser?.close().catch(() => undefined);
    this.browser = null;
  }

  health(): { browser_connected: boolean; sessions: string[]; lifecycle_metrics: BrowserLifecycleMetrics } {
    return {
      browser_connected: this.browser?.isConnected() ?? false,
      sessions: [...this.sessions.keys()].sort(),
      lifecycle_metrics: { ...this.metrics },
    };
  }

  private async ensureBrowser(): Promise<Browser> {
    if (this.browser?.isConnected()) return this.browser;
    this.sessions.clear();
    if (this.launchedOnce) this.metrics.browser_restarts += 1;
    this.browser = await this.launchBrowser({ headless: this.headless, ...browserExecutableOptions() });
    this.launchedOnce = true;
    this.browser.on("disconnected", () => {
      this.browser = null;
      this.sessions.clear();
    });
    return this.browser;
  }

  private async getSession(sourceId: string): Promise<AirlineSession> {
    const existing = this.sessions.get(sourceId);
    return existing ?? this.createSession(sourceId);
  }

  private async createSession(sourceId: string): Promise<AirlineSession> {
    const browser = await this.ensureBrowser();
    const context = await browser.newContext({ locale: "zh-CN", timezoneId: "Asia/Shanghai" });
    await context.route("**/*", async (route) => {
      const type = route.request().resourceType();
      if (["image", "font", "media"].includes(type)) await route.abort();
      else await route.continue();
    });
    const page = await context.newPage();
    const session = { context, page };
    this.sessions.set(sourceId, session);
    return session;
  }

  private async rebuildSession(sourceId: string): Promise<void> {
    const previous = this.sessions.get(sourceId);
    this.sessions.delete(sourceId);
    await previous?.context.close().catch(() => undefined);
    this.metrics.context_rebuilds += 1;
    await this.createSession(sourceId);
  }

  private async rebuildPage(sourceId: string): Promise<void> {
    const session = this.sessions.get(sourceId);
    if (!session) {
      await this.createSession(sourceId);
      return;
    }
    try {
      session.page = await session.context.newPage();
      this.metrics.page_rebuilds += 1;
    } catch {
      await this.rebuildSession(sourceId);
    }
  }
}

function challengeError(challenge: ChallengeResult): WorkerSearchError {
  return new WorkerSearchError(`AIRLINE_${challenge.code}`, challenge.message, true, challenge);
}

function numberEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}

export function browserExecutableOptions(): { executablePath?: string } {
  const executablePath = process.env.BROWSER_WORKER_EXECUTABLE_PATH?.trim();
  if (!executablePath) return {};
  if (!isAbsolute(executablePath) || !existsSync(executablePath)) {
    throw new WorkerSearchError(
      "BROWSER_EXECUTABLE_INVALID",
      "BROWSER_WORKER_EXECUTABLE_PATH must be an existing absolute file",
      false,
    );
  }
  return { executablePath };
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new WorkerSearchError("WORKER_ABORTED", "browser search was cancelled", true);
}

function isAbortError(error: unknown): boolean {
  return error instanceof WorkerSearchError && error.code === "WORKER_ABORTED";
}

function raceWithAbort<T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return operation;
  throwIfAborted(signal);
  return new Promise<T>((resolve, reject) => {
    const onAbort = (): void => reject(new WorkerSearchError("WORKER_ABORTED", "browser search was cancelled", true));
    signal.addEventListener("abort", onAbort, { once: true });
    void operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}
