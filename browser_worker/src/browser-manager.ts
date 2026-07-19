import { chromium, type Browser, type BrowserContext, type Page, type Response } from "playwright";

import type { BrowserFlightResult, ChallengeResult, FlightSearchInput } from "./contracts.js";
import { WorkerSearchError } from "./errors.js";
import type { AirlineBrowserHandler } from "./airlines/types.js";

interface AirlineSession {
  context: BrowserContext;
  page: Page;
}

export interface BrowserExecutionResult extends BrowserFlightResult {
  navigation_ms: number;
  response_ms: number;
  parse_ms: number;
}

export class BrowserManager {
  private browser: Browser | null = null;
  private readonly sessions = new Map<string, AirlineSession>();

  constructor(
    private readonly handlers: Map<string, AirlineBrowserHandler>,
    private readonly headless = process.env.BROWSER_WORKER_HEADLESS?.toLowerCase() !== "false",
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

  async execute(input: FlightSearchInput): Promise<BrowserExecutionResult> {
    const handler = this.handlers.get(input.source_id);
    if (!handler) throw new WorkerSearchError("SOURCE_NOT_IMPLEMENTED", `${input.source_id} is not implemented`, false);
    let session = await this.getSession(input.source_id);
    if (session.page.isClosed()) {
      await this.rebuildSession(input.source_id);
      session = await this.getSession(input.source_id);
    }
    const navigationStarted = performance.now();
    const targetResponse = session.page.waitForResponse(
      (response) => handler.matchesResponse(response, input),
      { timeout: numberEnv("BROWSER_WORKER_RESPONSE_TIMEOUT_MS", 15_000, 1_000, 60_000) },
    );
    let response: Response;
    let navigationFinished = navigationStarted;
    try {
      await handler.triggerSearch(session.page, input);
      navigationFinished = performance.now();
      response = await targetResponse;
    } catch (error) {
      void targetResponse.catch(() => undefined);
      const challenge = await handler.detectChallenge(session.page).catch(() => null);
      if (challenge) throw challengeError(challenge);
      if (session.page.isClosed()) await this.rebuildSession(input.source_id).catch(() => undefined);
      throw error;
    }
    const responseAt = performance.now();
    const challenge = await handler.detectChallenge(session.page, response);
    if (challenge) throw challengeError(challenge);
    const parseStarted = performance.now();
    const result = await handler.parseResponse(response, session.page, input);
    const finished = performance.now();
    return {
      ...result,
      navigation_ms: Math.max(0, Math.round(navigationFinished - navigationStarted)),
      response_ms: Math.max(0, Math.round(responseAt - navigationFinished)),
      parse_ms: Math.max(0, Math.round(finished - parseStarted)),
    };
  }

  async stop(): Promise<void> {
    this.sessions.clear();
    await this.browser?.close().catch(() => undefined);
    this.browser = null;
  }

  health(): { browser_connected: boolean; sessions: string[] } {
    return {
      browser_connected: this.browser?.isConnected() ?? false,
      sessions: [...this.sessions.keys()].sort(),
    };
  }

  private async ensureBrowser(): Promise<Browser> {
    if (this.browser?.isConnected()) return this.browser;
    this.sessions.clear();
    this.browser = await chromium.launch({ headless: this.headless });
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
    await this.createSession(sourceId);
  }
}

function challengeError(challenge: ChallengeResult): WorkerSearchError {
  return new WorkerSearchError(`AIRLINE_${challenge.code}`, challenge.message, true, challenge);
}

function numberEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}
