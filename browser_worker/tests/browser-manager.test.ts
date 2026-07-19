import assert from "node:assert/strict";
import test from "node:test";

import type { Browser, BrowserContext, LaunchOptions, Page, Response } from "playwright";

import type { AirlineBrowserHandler } from "../src/airlines/types.js";
import { browserExecutableOptions } from "../src/browser-manager.js";
import { BrowserManager } from "../src/browser-manager.js";
import type { FlightSearchInput } from "../src/contracts.js";

const input: FlightSearchInput = {
  request_id: "recovery-test",
  source_id: "airline_mu_browser_query",
  origin_iata: "PVG",
  destination_iata: "PEK",
  departure_date: "2026-07-23",
  adults: 1,
  currency_code: "CNY",
  max_results: 5,
};

test("browser executable override is optional and invalid paths fail closed", () => {
  const previous = process.env.BROWSER_WORKER_EXECUTABLE_PATH;
  try {
    delete process.env.BROWSER_WORKER_EXECUTABLE_PATH;
    assert.deepEqual(browserExecutableOptions(), {});
    process.env.BROWSER_WORKER_EXECUTABLE_PATH = "relative/chromium";
    assert.throws(() => browserExecutableOptions(), /existing absolute file/);
  } finally {
    if (previous === undefined) delete process.env.BROWSER_WORKER_EXECUTABLE_PATH;
    else process.env.BROWSER_WORKER_EXECUTABLE_PATH = previous;
  }
});

test("a closed page is rebuilt without replacing its airline context", async () => {
  const runtime = fakeRuntime();
  const manager = new BrowserManager(new Map([[handler.sourceId, handler]]), true, runtime.launch);
  await manager.start([handler.sourceId]);
  runtime.pages[0]!.closed = true;

  const result = await manager.execute(input);

  assert.equal(result.evidence_id, "recovery_evidence");
  assert.equal(runtime.launches, 1);
  assert.equal(runtime.contexts, 1);
  assert.equal(runtime.pages.length, 2);
  assert.equal(manager.metrics.page_rebuilds, 1);
  assert.equal(manager.metrics.context_rebuilds, 0);
  await manager.stop();
});

test("a context that cannot create a replacement page is rebuilt in isolation", async () => {
  const runtime = fakeRuntime({ failSecondPageInFirstContext: true });
  const manager = new BrowserManager(new Map([[handler.sourceId, handler]]), true, runtime.launch);
  await manager.start([handler.sourceId]);
  runtime.pages[0]!.closed = true;

  await manager.execute(input);

  assert.equal(runtime.launches, 1);
  assert.equal(runtime.contexts, 2);
  assert.equal(manager.metrics.context_rebuilds, 1);
  await manager.stop();
});

test("a stopped browser is launched again without restarting the worker process", async () => {
  const runtime = fakeRuntime();
  const manager = new BrowserManager(new Map([[handler.sourceId, handler]]), true, runtime.launch);
  await manager.start([handler.sourceId]);
  await manager.stop();

  await manager.execute(input);

  assert.equal(runtime.launches, 2);
  assert.equal(manager.metrics.browser_restarts, 1);
  await manager.stop();
});

test("an aborted query stops waiting before response parsing", async () => {
  let parsed = false;
  const blockingHandler: AirlineBrowserHandler = {
    ...handler,
    async triggerSearch(): Promise<void> {
      await new Promise<void>(() => undefined);
    },
    async parsePage() {
      parsed = true;
      return { flights: [], evidence_id: "should_not_parse" };
    },
  };
  const runtime = fakeRuntime();
  const manager = new BrowserManager(new Map([[blockingHandler.sourceId, blockingHandler]]), true, runtime.launch);
  await manager.start([blockingHandler.sourceId]);
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 5);

  await assert.rejects(manager.execute(input, controller.signal), (error: unknown) => {
    return error instanceof Error && "code" in error && error.code === "WORKER_ABORTED";
  });
  assert.equal(parsed, false);
  await manager.stop();
});

const handler: AirlineBrowserHandler = {
  sourceId: "airline_mu_browser_query",
  async warmUp(): Promise<void> {},
  async triggerSearch(): Promise<void> {},
  matchesResponse(): boolean {
    return false;
  },
  async parseResponse() {
    return { flights: [], evidence_id: "response_evidence" };
  },
  async waitForPageResult(): Promise<void> {},
  async parsePage() {
    return { flights: [], evidence_id: "recovery_evidence" };
  },
  async detectChallenge() {
    return null;
  },
};

interface FakePageState {
  closed: boolean;
}

function fakeRuntime(options: { failSecondPageInFirstContext?: boolean } = {}): {
  launch: (launchOptions: LaunchOptions) => Promise<Browser>;
  readonly launches: number;
  readonly contexts: number;
  pages: FakePageState[];
} {
  let launches = 0;
  let contexts = 0;
  const pages: FakePageState[] = [];
  const launch = async (_launchOptions: LaunchOptions): Promise<Browser> => {
    launches += 1;
    let connected = true;
    const browser = {
      isConnected: () => connected,
      on: () => browser,
      close: async () => {
        connected = false;
      },
      newContext: async (): Promise<BrowserContext> => {
        contexts += 1;
        const contextNumber = contexts;
        let pageCalls = 0;
        const context = {
          route: async () => undefined,
          close: async () => undefined,
          newPage: async (): Promise<Page> => {
            pageCalls += 1;
            if (options.failSecondPageInFirstContext && contextNumber === 1 && pageCalls === 2) {
              throw new Error("context closed");
            }
            const state: FakePageState = { closed: false };
            pages.push(state);
            const page = {
              isClosed: () => state.closed,
              waitForResponse: async () => new Promise<Response>(() => undefined),
            };
            return page as unknown as Page;
          },
        };
        return context as unknown as BrowserContext;
      },
    };
    return browser as unknown as Browser;
  };
  return {
    launch,
    get launches() {
      return launches;
    },
    get contexts() {
      return contexts;
    },
    pages,
  };
}
