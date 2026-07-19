import assert from "node:assert/strict";
import test from "node:test";

import { parseFlightSearchInput, searchKey } from "../src/contracts.js";

test("flight-search input is normalized and stable", () => {
  const input = parseFlightSearchInput({
    request_id: "req-1",
    source_id: "airline_mu_browser_query",
    origin_iata: "pvg",
    destination_iata: "tao",
    departure_date: "2026-07-23",
    adults: 1,
    currency_code: "cny",
    max_results: 5,
  });

  assert.equal(input.origin_iata, "PVG");
  assert.match(searchKey(input), /airline_mu_browser_query:PVG:TAO:2026-07-23/);
});

test("unknown sources and invalid routes fail closed", () => {
  assert.throws(() =>
    parseFlightSearchInput({
      request_id: "req-1",
      source_id: "airline_ca_browser_query",
      origin_iata: "PEK",
      destination_iata: "SHA",
      departure_date: "2026-07-23",
      adults: 1,
      currency_code: "CNY",
      max_results: 5,
    }),
  );
  assert.throws(() =>
    parseFlightSearchInput({
      request_id: "req-1",
      source_id: "airline_mu_browser_query",
      origin_iata: "PVG",
      destination_iata: "PVG",
      departure_date: "2026-07-23",
      adults: 1,
      currency_code: "CNY",
      max_results: 5,
    }),
  );
});
