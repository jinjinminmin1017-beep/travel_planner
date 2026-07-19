import { createHash, randomUUID } from "node:crypto";

import type { Page, Response } from "playwright";

import {
  isRecord,
  type BrowserFare,
  type BrowserFlight,
  type BrowserFlightResult,
  type ChallengeResult,
  type FlightSearchInput,
} from "../contracts.js";
import { WorkerSearchError } from "../errors.js";
import type { AirlineBrowserHandler } from "./types.js";

const MU_HOME_URL = "https://www.ceair.com/zh/cny/home";
const MU_RESPONSE_PATH = "/portal/v3/shopping/briefInfo";
const MU_ALLOWED_HOSTS = ["ceair.com"];
const MU_RESULT_URL_TEMPLATE =
  "https://www.ceair.com/zh/cny/shopping/oneway/{origin_iata}-{destination_iata}/{departure_date}";
const MU_RESULT_CARD_SELECTOR = ".shopping-simple";
const CHALLENGE_TEXT = ["验证码", "安全验证", "访问过于频繁", "当前访问的人太多", "verify", "captcha"];

export interface MuDomRow {
  flightNumber: string;
  departureTime: string;
  arrivalTime: string;
  fares: Array<string | null>;
}

export class MuAirlineHandler implements AirlineBrowserHandler {
  readonly sourceId = "airline_mu_browser_query" as const;

  constructor(
    private readonly resultUrlTemplate = process.env.MU_RESULT_URL_TEMPLATE?.trim() || MU_RESULT_URL_TEMPLATE,
  ) {}

  async warmUp(page: Page): Promise<void> {
    await page.goto(MU_HOME_URL, { waitUntil: "domcontentloaded", timeout: 15_000 });
  }

  async triggerSearch(page: Page, input: FlightSearchInput): Promise<void> {
    const resultUrl = buildMuResultUrl(input, this.resultUrlTemplate);
    assertAllowedUrl(resultUrl);
    await page.goto(resultUrl, { waitUntil: "domcontentloaded", timeout: 15_000 });
  }

  matchesResponse(response: Response, input: FlightSearchInput): boolean {
    const request = response.request();
    const url = new URL(response.url());
    if (!hostAllowed(url.hostname) || url.pathname !== MU_RESPONSE_PATH) {
      return false;
    }
    if (request.method() !== "POST" || !["xhr", "fetch"].includes(request.resourceType())) {
      return false;
    }
    if (response.status() !== 200 || !response.headers()["content-type"]?.toLowerCase().includes("json")) {
      return false;
    }
    const postData = request.postData();
    if (!postData) {
      return false;
    }
    return requestMatchesInput(postData, input);
  }

  async parseResponse(response: Response, page: Page, input: FlightSearchInput): Promise<BrowserFlightResult> {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    try {
      return await this.parsePage(page, input);
    } catch (error) {
      if (isExplicitEmptyResult(payload)) return result([]);
      if (error instanceof WorkerSearchError) throw error;
      throw new WorkerSearchError("MU_RESPONSE_STRUCTURE_CHANGED", "China Eastern result structure changed", true);
    }
  }

  async waitForPageResult(page: Page, input: FlightSearchInput): Promise<void> {
    assertResultPageMatchesInput(page.url(), input);
    await page.locator(MU_RESULT_CARD_SELECTOR).first().waitFor({
      state: "visible",
      timeout: numberEnv("BROWSER_WORKER_RESPONSE_TIMEOUT_MS", 15_000, 1_000, 60_000),
    });
  }

  async parsePage(page: Page, input: FlightSearchInput): Promise<BrowserFlightResult> {
    assertResultPageMatchesInput(page.url(), input);
    await dismissPublicNotice(page);
    await ensureTaxInclusive(page);
    await page.locator(MU_RESULT_CARD_SELECTOR).first().waitFor({ state: "visible", timeout: 5_000 });
    const rows = await page.locator(MU_RESULT_CARD_SELECTOR).evaluateAll((cards) =>
      cards.slice(0, 40).map((card) => ({
        flightNumber: card.querySelector(".title-flight-no")?.textContent?.trim() ?? "",
        departureTime: card.querySelector(".flight-info-dep-time")?.textContent?.trim() ?? "",
        arrivalTime: card.querySelector(".flight-info-arr-time")?.textContent?.trim() ?? "",
        fares: Array.from(card.querySelectorAll(".cabin-level-item")).map((item) => {
          const text = item.textContent?.replace(/\s+/g, " ").trim() ?? "";
          return text.includes("—") ? null : text;
        }),
      })),
    );
    const flights = parseMuDomRows(rows, input).slice(0, input.max_results);
    if (flights.length === 0) {
      throw new WorkerSearchError(
        "MU_DOM_STRUCTURE_CHANGED",
        "China Eastern page did not contain a verified priced MU/FM flight",
        true,
      );
    }
    return result(flights);
  }

  async detectChallenge(page: Page, response?: Response): Promise<ChallengeResult | null> {
    if (response?.status() === 429) {
      return { code: "RATE_LIMIT", message: "airline returned rate limit" };
    }
    if (response && [403, 418, 503].includes(response.status())) {
      return { code: "WAF", message: "airline returned a risk-control response" };
    }
    const title = await page.title().catch(() => "");
    const bodyText = await page.locator("body").innerText({ timeout: 2_000 }).catch(() => "");
    const text = `${title}\n${bodyText}`.toLowerCase();
    if (CHALLENGE_TEXT.some((marker) => text.includes(marker.toLowerCase()))) {
      return { code: "CAPTCHA", message: "airline challenge page detected" };
    }
    return null;
  }
}

export function parseMuDomRows(rows: MuDomRow[], input: FlightSearchInput): BrowserFlight[] {
  const cabinTypes: BrowserFare["cabin_type"][] = ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"];
  const flights: BrowserFlight[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const fullFlightNumber = row.flightNumber.replace(/\s+/g, "").toUpperCase();
    const match = /^(MU|FM)(\d{3,4}[A-Z]?)$/.exec(fullFlightNumber);
    const departureAt = chinaDateTime(row.departureTime, input.departure_date);
    let arrivalAt = chinaDateTime(row.arrivalTime, input.departure_date);
    if (!match || !departureAt || !arrivalAt) continue;
    if (Date.parse(arrivalAt) <= Date.parse(departureAt)) {
      arrivalAt = formatShanghai(new Date(Date.parse(arrivalAt) + 24 * 60 * 60 * 1_000));
    }
    const fares = row.fares.slice(0, cabinTypes.length).flatMap((rawPrice, index) => {
      const price = displayedPriceMinor(rawPrice);
      const cabin = cabinTypes[index];
      if (price === null || cabin === undefined) return [];
      return [
        {
          fare_id: `${fullFlightNumber.toLowerCase()}_${cabin.toLowerCase()}_${price}`,
          cabin_type: cabin,
          price: { amount_minor: price, currency: input.currency_code, scale: 2 as const },
          availability: "AVAILABLE" as const,
        },
      ];
    });
    if (fares.length === 0) continue;
    const key = `${fullFlightNumber}:${departureAt}:${input.origin_iata}:${input.destination_iata}`;
    if (seen.has(key)) continue;
    seen.add(key);
    flights.push({
      flight_id: `mu_${createHash("sha256").update(key).digest("hex").slice(0, 16)}`,
      carrier_code: match[1] as "MU" | "FM",
      flight_number: match[2] as string,
      origin_iata: input.origin_iata,
      destination_iata: input.destination_iata,
      departure_at: departureAt,
      arrival_at: arrivalAt,
      fares,
    });
  }
  return flights.sort((left, right) => left.departure_at.localeCompare(right.departure_at));
}

export function requestMatchesInput(postData: string, input: FlightSearchInput): boolean {
  let normalized: string;
  try {
    normalized = decodeURIComponent(postData).toUpperCase();
  } catch {
    return false;
  }
  const compactDate = input.departure_date.replaceAll("-", "");
  return (
    normalized.includes(input.origin_iata) &&
    normalized.includes(input.destination_iata) &&
    (normalized.includes(input.departure_date) || normalized.includes(compactDate)) &&
    containsAdults(normalized, input.adults)
  );
}

export function parseMuPayload(payload: unknown, input: FlightSearchInput): BrowserFlight[] {
  const records = collectRecords(payload);
  const flights: BrowserFlight[] = [];
  const seen = new Set<string>();
  for (const record of records) {
    const fullFlightNumber = stringField(record, ["flightNo", "flightNumber", "flight_no"]).toUpperCase();
    const match = /^(MU|FM)(\d{3,4}[A-Z]?)$/.exec(fullFlightNumber);
    if (!match) {
      continue;
    }
    const origin = stringField(record, ["originAirport", "departureAirport", "origin", "orgCode", "depAirportCode"]).toUpperCase();
    const destination = stringField(record, ["destinationAirport", "arrivalAirport", "destination", "dstCode", "arrAirportCode"]).toUpperCase();
    if (origin !== input.origin_iata || destination !== input.destination_iata) {
      continue;
    }
    const departureAt = chinaDateTime(
      field(record, ["departureTime", "departureDateTime", "departure_at", "depTime"]),
      input.departure_date,
    );
    let arrivalAt = chinaDateTime(
      field(record, ["arrivalTime", "arrivalDateTime", "arrival_at", "arrTime"]),
      input.departure_date,
    );
    if (!departureAt || !arrivalAt) {
      continue;
    }
    if (Date.parse(arrivalAt) <= Date.parse(departureAt)) {
      arrivalAt = formatShanghai(new Date(Date.parse(arrivalAt) + 24 * 60 * 60 * 1_000));
    }
    const fares = faresFromRecord(record, input.currency_code, fullFlightNumber);
    if (fares.length === 0) {
      continue;
    }
    const key = `${fullFlightNumber}:${departureAt}:${origin}:${destination}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    flights.push({
      flight_id: `mu_${createHash("sha256").update(key).digest("hex").slice(0, 16)}`,
      carrier_code: match[1] as "MU" | "FM",
      flight_number: match[2] as string,
      origin_iata: origin,
      destination_iata: destination,
      departure_at: departureAt,
      arrival_at: arrivalAt,
      fares,
    });
  }
  return flights.sort((left, right) => left.departure_at.localeCompare(right.departure_at));
}

function faresFromRecord(record: Record<string, unknown>, currencyCode: string, flightNumber: string): BrowserFare[] {
  const candidates = arrayField(record, ["fares", "fareOptions", "cabins", "products", "prices"]);
  const fareRecords = candidates.length > 0 ? candidates.filter(isRecord) : [record];
  const fares: BrowserFare[] = [];
  for (const [index, fare] of fareRecords.entries()) {
    const price = priceMinor(fare);
    const availability = fareAvailability(fare);
    if (price === null || price <= 0 || availability === null) {
      continue;
    }
    const cabinCode = stringField(fare, ["cabinType", "cabinClass", "cabinCode", "cabin", "classCode"]);
    const remaining = remainingCount(fare);
    fares.push({
      fare_id: `${flightNumber.toLowerCase()}_${normalizeToken(cabinCode || "economy")}_${index + 1}_${price}`,
      cabin_type: cabinType(cabinCode),
      price: { amount_minor: price, currency: currencyCode, scale: 2 },
      availability: remaining !== null && remaining <= 9 ? "LIMITED" : availability,
      ...(remaining !== null ? { remaining_count: remaining } : {}),
    });
  }
  return fares;
}

function priceMinor(record: Record<string, unknown>): number | null {
  const directMinor = field(record, ["amountMinor", "amount_minor"]);
  if (Number.isInteger(directMinor) && (directMinor as number) > 0) {
    return directMinor as number;
  }
  const raw = field(record, ["price", "adultPrice", "ticketPrice", "salePrice", "amount"]);
  const value = typeof raw === "number" ? raw : Number.parseFloat(String(raw ?? "").replace(/[^0-9.]/g, ""));
  return Number.isFinite(value) && value > 0 ? Math.round(value * 100) : null;
}

function fareAvailability(record: Record<string, unknown>): BrowserFare["availability"] | null {
  const status = stringField(record, ["availability", "status", "inventoryStatus", "seatStatus"]).toUpperCase();
  if (["SOLD_OUT", "UNAVAILABLE", "CLOSED", "0", "无票", "售罄"].includes(status)) return null;
  const available = field(record, ["available", "isAvailable", "canSell"]);
  if (available === false) return null;
  const remaining = remainingCount(record);
  if (remaining !== null) return remaining <= 9 ? "LIMITED" : "AVAILABLE";
  if (available === true || ["AVAILABLE", "LIMITED", "OPEN", "ON_SALE", "A", "有票"].includes(status)) {
    return status === "LIMITED" ? "LIMITED" : "AVAILABLE";
  }
  return null;
}

function remainingCount(record: Record<string, unknown>): number | null {
  const raw = field(record, ["remainingCount", "remaining", "seatCount", "inventory"]);
  const parsed = typeof raw === "number" ? raw : Number.parseInt(String(raw ?? ""), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function cabinType(raw: string): BrowserFare["cabin_type"] {
  const value = raw.toUpperCase();
  if (value.includes("FIRST") || value.includes("头等") || value === "F") return "FIRST";
  if (value.includes("BUSINESS") || value.includes("公务") || value.includes("商务") || value === "C") return "BUSINESS";
  if (value.includes("PREMIUM") || value.includes("超级经济") || value === "W") return "PREMIUM_ECONOMY";
  return "ECONOMY";
}

function chinaDateTime(value: unknown, fallbackDate: string): string | null {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const normalized = /^\d{1,2}:\d{2}$/.test(text) ? `${fallbackDate}T${text}:00+08:00` : text.replace(" ", "T");
  const withZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(normalized) ? normalized : `${normalized}+08:00`;
  const timestamp = Date.parse(withZone);
  if (Number.isNaN(timestamp)) return null;
  return formatShanghai(new Date(timestamp));
}

function formatShanghai(value: Date): string {
  return value.toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", hour12: false }).replace(" ", "T") + "+08:00";
}

function collectRecords(value: unknown, depth = 0): Record<string, unknown>[] {
  if (depth > 8) return [];
  if (Array.isArray(value)) return value.flatMap((item) => collectRecords(item, depth + 1));
  if (!isRecord(value)) return [];
  return [value, ...Object.values(value).flatMap((item) => collectRecords(item, depth + 1))];
}

function isExplicitEmptyResult(payload: unknown): boolean {
  if (!isRecord(payload)) return false;
  const records = [payload, payload.data, payload.result].filter(isRecord);
  return records.some((record) => {
    const count = field(record, ["total", "totalCount", "flightCount"]);
    const status = stringField(record, ["status", "code", "resultCode"]).toUpperCase();
    const flightValue = field(record, ["flights", "flightList", "results"]);
    return (
      count === 0 ||
      ["NO_FLIGHT", "EMPTY", "NO_RESULT"].includes(status) ||
      (Array.isArray(flightValue) && flightValue.length === 0)
    );
  });
}

async function dismissPublicNotice(page: Page): Promise<void> {
  const acknowledgement = page.getByRole("button", { name: "我知道了", exact: true });
  const count = await acknowledgement.count();
  if (count > 1) {
    throw new WorkerSearchError("MU_NOTICE_STRUCTURE_CHANGED", "China Eastern notice controls are ambiguous", true);
  }
  if (count === 1 && (await acknowledgement.isVisible())) {
    await acknowledgement.click({ timeout: 3_000 });
  }
}

async function ensureTaxInclusive(page: Page): Promise<void> {
  const radio = page.getByRole("radio", { name: "现金-含税", exact: true });
  if ((await radio.count()) !== 1) {
    throw new WorkerSearchError("MU_TAX_MODE_UNAVAILABLE", "China Eastern tax-inclusive price control is unavailable", true);
  }
  if ((await radio.getAttribute("aria-checked")) !== "true") {
    await radio.click({ timeout: 3_000 });
  }
  if ((await radio.getAttribute("aria-checked")) !== "true") {
    throw new WorkerSearchError("MU_TAX_MODE_UNAVAILABLE", "China Eastern tax-inclusive price was not selected", true);
  }
  await page.waitForTimeout(250);
}

export function assertResultPageMatchesInput(value: string, input: FlightSearchInput): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new WorkerSearchError("MU_RESULT_PAGE_MISMATCH", "China Eastern result page URL is invalid", true);
  }
  const segments = decodeURIComponent(url.pathname).split("/").filter(Boolean);
  const date = segments.at(-1);
  const route = segments.at(-2)?.toUpperCase() ?? "";
  const [origins = "", destinations = ""] = route.split("-", 2);
  const airportCodes = (part: string): string[] => part.match(/[A-Z]{3}/g) ?? [];
  if (
    !hostAllowed(url.hostname) ||
    url.protocol !== "https:" ||
    !url.pathname.includes("/shopping/oneway/") ||
    date !== input.departure_date ||
    !airportCodes(origins).includes(input.origin_iata) ||
    !airportCodes(destinations).includes(input.destination_iata)
  ) {
    throw new WorkerSearchError("MU_RESULT_PAGE_MISMATCH", "China Eastern result page does not match the request", true);
  }
}

function displayedPriceMinor(value: string | null): number | null {
  if (!value || value.includes("—")) return null;
  const matches = value.replaceAll(",", "").match(/(?:¥|CNY|￥)\s*(\d+(?:\.\d{1,2})?)/i);
  if (!matches?.[1]) return null;
  const amount = Number.parseFloat(matches[1]);
  return Number.isFinite(amount) && amount > 0 ? Math.round(amount * 100) : null;
}

function result(flights: BrowserFlight[]): BrowserFlightResult {
  return {
    flights,
    evidence_id: `mubw_${randomUUID().replaceAll("-", "").slice(0, 16)}`,
  };
}

export function buildMuResultUrl(input: FlightSearchInput, template = MU_RESULT_URL_TEMPLATE): string {
  return template
    .replaceAll("{origin_iata}", encodeURIComponent(input.origin_iata))
    .replaceAll("{destination_iata}", encodeURIComponent(input.destination_iata))
    .replaceAll("{departure_date}", encodeURIComponent(input.departure_date))
    .replaceAll("{adults}", String(input.adults))
    .replaceAll("{currency_code}", encodeURIComponent(input.currency_code));
}

function assertAllowedUrl(value: string): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new WorkerSearchError("MU_RESULT_URL_INVALID", "China Eastern result URL template is invalid", false);
  }
  if (url.protocol !== "https:" || !hostAllowed(url.hostname) || /\{[^}]+\}/.test(value)) {
    throw new WorkerSearchError("MU_RESULT_URL_INVALID", "China Eastern result URL is outside the allowlist", false);
  }
}

function hostAllowed(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  return MU_ALLOWED_HOSTS.some((host) => normalized === host || normalized.endsWith(`.${host}`));
}

function containsAdults(postData: string, adults: number): boolean {
  const patterns = [
    new RegExp(`"(?:ADULTS?|ADT|PASSENGERCOUNT)"\\s*:\\s*${adults}(?:[,}])`, "i"),
    new RegExp(`(?:ADULTS?|ADT|PASSENGERCOUNT)=${adults}(?:&|$)`, "i"),
  ];
  return patterns.some((pattern) => pattern.test(postData));
}

function field(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key];
  }
  return undefined;
}

function stringField(record: Record<string, unknown>, keys: string[]): string {
  return String(field(record, keys) ?? "").trim();
}

function arrayField(record: Record<string, unknown>, keys: string[]): unknown[] {
  const value = field(record, keys);
  return Array.isArray(value) ? value : [];
}

function normalizeToken(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return normalized || "option";
}

function numberEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}
