export const SUPPORTED_SOURCE_IDS = ["airline_mu_browser_query"] as const;

export type SupportedSourceId = (typeof SUPPORTED_SOURCE_IDS)[number];

export interface FlightSearchInput {
  request_id: string;
  source_id: SupportedSourceId;
  origin_iata: string;
  destination_iata: string;
  departure_date: string;
  adults: number;
  currency_code: string;
  max_results: number;
}

export interface BrowserMoney {
  amount_minor: number;
  currency: string;
  scale: number;
}

export interface BrowserFare {
  fare_id: string;
  cabin_type: "ECONOMY" | "PREMIUM_ECONOMY" | "BUSINESS" | "FIRST";
  price: BrowserMoney;
  availability: "AVAILABLE" | "LIMITED";
  remaining_count?: number;
}

export interface BrowserFlight {
  flight_id: string;
  carrier_code: "MU" | "FM";
  flight_number: string;
  origin_iata: string;
  destination_iata: string;
  departure_at: string;
  arrival_at: string;
  fares: BrowserFare[];
}

export interface ChallengeResult {
  code: "CAPTCHA" | "WAF" | "RATE_LIMIT" | "RISK_CONTROL";
  message: string;
}

export interface BrowserFlightResult {
  flights: BrowserFlight[];
  evidence_id: string;
}

export interface SearchTimings {
  queue_ms: number;
  navigation_ms: number;
  response_ms: number;
  parse_ms: number;
  total_ms: number;
}

export interface FlightSearchSuccess extends SearchTimings {
  success: true;
  source_id: SupportedSourceId;
  flights: BrowserFlight[];
  evidence_id: string;
  cache_hit: boolean;
}

export interface FlightSearchFailure extends SearchTimings {
  success: false;
  source_id: SupportedSourceId;
  flights: [];
  error_code: string;
  message: string;
  retryable: boolean;
  challenge?: ChallengeResult;
}

export type FlightSearchResponse = FlightSearchSuccess | FlightSearchFailure;

export function parseFlightSearchInput(value: unknown): FlightSearchInput {
  if (!isRecord(value)) {
    throw new Error("request body must be an object");
  }
  const sourceId = requiredString(value, "source_id");
  if (!SUPPORTED_SOURCE_IDS.includes(sourceId as SupportedSourceId)) {
    throw new Error("source_id is not implemented");
  }
  const input: FlightSearchInput = {
    request_id: requiredString(value, "request_id", 128),
    source_id: sourceId as SupportedSourceId,
    origin_iata: iata(value, "origin_iata"),
    destination_iata: iata(value, "destination_iata"),
    departure_date: isoDate(value, "departure_date"),
    adults: integer(value, "adults", 1, 9),
    currency_code: currency(value, "currency_code"),
    max_results: integer(value, "max_results", 1, 20),
  };
  if (input.origin_iata === input.destination_iata) {
    throw new Error("origin_iata and destination_iata must differ");
  }
  return input;
}

export function searchKey(input: FlightSearchInput): string {
  return [
    input.source_id,
    input.origin_iata,
    input.destination_iata,
    input.departure_date,
    input.adults,
    input.currency_code,
    input.max_results,
  ].join(":");
}

function requiredString(value: Record<string, unknown>, key: string, maxLength = 64): string {
  const raw = value[key];
  if (typeof raw !== "string" || raw.trim() === "" || raw.length > maxLength) {
    throw new Error(`${key} is invalid`);
  }
  return raw.trim();
}

function iata(value: Record<string, unknown>, key: string): string {
  const parsed = requiredString(value, key).toUpperCase();
  if (!/^[A-Z]{3}$/.test(parsed)) {
    throw new Error(`${key} is invalid`);
  }
  return parsed;
}

function currency(value: Record<string, unknown>, key: string): string {
  const parsed = requiredString(value, key).toUpperCase();
  if (!/^[A-Z]{3}$/.test(parsed)) {
    throw new Error(`${key} is invalid`);
  }
  return parsed;
}

function isoDate(value: Record<string, unknown>, key: string): string {
  const parsed = requiredString(value, key);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(parsed) || Number.isNaN(Date.parse(`${parsed}T00:00:00+08:00`))) {
    throw new Error(`${key} is invalid`);
  }
  return parsed;
}

function integer(value: Record<string, unknown>, key: string, minimum: number, maximum: number): number {
  const parsed = value[key];
  if (!Number.isInteger(parsed) || (parsed as number) < minimum || (parsed as number) > maximum) {
    throw new Error(`${key} is invalid`);
  }
  return parsed as number;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
