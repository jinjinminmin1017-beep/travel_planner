import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { MuAirlineHandler } from "./airlines/mu.js";
import { BrowserManager } from "./browser-manager.js";
import { parseFlightSearchInput } from "./contracts.js";
import { SessionPool } from "./session-pool.js";

const host = process.env.BROWSER_WORKER_HOST?.trim() || "127.0.0.1";
if (!["127.0.0.1", "::1", "localhost"].includes(host)) {
  throw new Error("BROWSER_WORKER_HOST must be loopback");
}
const port = numberEnv("BROWSER_WORKER_PORT", 4319, 1, 65_535);
const enabledSourceIds = (process.env.BROWSER_WORKER_SOURCE_IDS || "airline_mu_browser_query")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);
const handlers = new Map([["airline_mu_browser_query", new MuAirlineHandler()]]);
const manager = new BrowserManager(handlers);
const pool = new SessionPool(manager);

await manager.start(enabledSourceIds);

const server = createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/health") {
      json(response, 200, { status: "ok", ...manager.health(), ...pool.health() });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/flight-search") {
      const body = await readJson(request);
      const input = parseFlightSearchInput(body);
      const result = await pool.search(input);
      json(response, 200, result);
      return;
    }
    json(response, 404, { error_code: "NOT_FOUND", message: "route not found" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    json(response, 400, { error_code: "INVALID_REQUEST", message });
  }
});

server.listen(port, host, () => {
  process.stdout.write(`browser_worker_listening host=${host} port=${port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close(() => {
      void manager.stop().finally(() => process.exit(0));
    });
  });
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > 64 * 1024) throw new Error("request body is too large");
    chunks.push(buffer);
  }
  const text = Buffer.concat(chunks).toString("utf8");
  return text ? JSON.parse(text) : null;
}

function json(response: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

function numberEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}
