import type { Page, Response } from "playwright";

import type { BrowserFlightResult, ChallengeResult, FlightSearchInput } from "../contracts.js";

export interface AirlineBrowserHandler {
  readonly sourceId: FlightSearchInput["source_id"];
  warmUp(page: Page): Promise<void>;
  triggerSearch(page: Page, input: FlightSearchInput): Promise<void>;
  matchesResponse(response: Response, input: FlightSearchInput): boolean;
  parseResponse(response: Response, page: Page, input: FlightSearchInput): Promise<BrowserFlightResult>;
  waitForPageResult?(page: Page, input: FlightSearchInput): Promise<void>;
  parsePage?(page: Page, input: FlightSearchInput): Promise<BrowserFlightResult>;
  matchesChallengeResponse?(response: Response): boolean;
  detectChallenge(page: Page, response?: Response): Promise<ChallengeResult | null>;
}
