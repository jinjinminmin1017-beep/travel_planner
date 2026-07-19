import assert from "node:assert/strict";
import test from "node:test";

import type { FlightSearchInput } from "../src/contracts.js";
import {
  assertResultPageMatchesInput,
  buildMuResultUrl,
  parseMuDomRows,
  parseMuPayload,
  requestMatchesInput,
} from "../src/airlines/mu.js";

const input: FlightSearchInput = {
  request_id: "req-mu",
  source_id: "airline_mu_browser_query",
  origin_iata: "PVG",
  destination_iata: "TAO",
  departure_date: "2026-07-23",
  adults: 1,
  currency_code: "CNY",
  max_results: 5,
};

test("MU response matching rejects stale route/date/passenger responses", () => {
  assert.equal(
    requestMatchesInput('{"origin":"PVG","destination":"TAO","departureDate":"2026-07-23","adults":1}', input),
    true,
  );
  assert.equal(
    requestMatchesInput('{"origin":"SHA","destination":"PEK","departureDate":"2026-07-23","adults":1}', input),
    false,
  );
  assert.equal(
    requestMatchesInput('{"origin":"PVG","destination":"TAO","departureDate":"2026-07-22","adults":1}', input),
    false,
  );
});

test("MU payload maps only matching, priced and available MU/FM flights", () => {
  const flights = parseMuPayload(
    {
      data: {
        flights: [
          {
            flightNo: "MU6863",
            originAirport: "PVG",
            destinationAirport: "TAO",
            departureTime: "2026-07-23 08:10:00",
            arrivalTime: "2026-07-23 09:45:00",
            fares: [
              { cabinType: "ECONOMY", price: 680, remainingCount: 4 },
              { cabinType: "BUSINESS", price: 1680, status: "SOLD_OUT" },
            ],
          },
          {
            flightNo: "FM9229",
            originAirport: "PVG",
            destinationAirport: "TAO",
            departureTime: "13:00",
            arrivalTime: "14:40",
            fares: [{ cabinCode: "C", amountMinor: 128000, availability: "AVAILABLE" }],
          },
          {
            flightNo: "MU9999",
            originAirport: "SHA",
            destinationAirport: "PEK",
            departureTime: "13:00",
            arrivalTime: "15:00",
            fares: [{ price: 999 }],
          },
        ],
      },
    },
    input,
  );

  assert.equal(flights.length, 2);
  assert.deepEqual(flights.map((flight) => `${flight.carrier_code}${flight.flight_number}`), ["MU6863", "FM9229"]);
  assert.equal(flights[0]?.fares[0]?.price.amount_minor, 68000);
  assert.equal(flights[0]?.fares[0]?.availability, "LIMITED");
  assert.equal(flights[1]?.fares[0]?.cabin_type, "BUSINESS");
});

test("encrypted or structurally unrelated payloads do not create offers", () => {
  assert.deepEqual(parseMuPayload({ data: { enc: "opaque-ciphertext" } }, input), []);
});

test("verified MU result URL is built from the exact airport pair and date", () => {
  assert.equal(
    buildMuResultUrl(input),
    "https://www.ceair.com/zh/cny/shopping/oneway/PVG-TAO/2026-07-23",
  );
  assert.doesNotThrow(() => assertResultPageMatchesInput(buildMuResultUrl(input), input));
  assert.throws(
    () => assertResultPageMatchesInput("https://www.ceair.com/zh/cny/shopping/oneway/SHA-PEK/2026-07-23", input),
    /does not match/,
  );
});

test("MU public DOM rows map tax-inclusive displayed fares without inventing unavailable cabins", () => {
  const flights = parseMuDomRows(
    [
      {
        flightNumber: "MU 5151",
        departureTime: "23:40",
        arrivalTime: "01:10",
        fares: ["¥ 934", null, "¥ 3,870"],
      },
      {
        flightNumber: "CA1234",
        departureTime: "09:00",
        arrivalTime: "11:00",
        fares: ["¥ 900", null, null],
      },
    ],
    input,
  );

  assert.equal(flights.length, 1);
  assert.equal(flights[0]?.carrier_code, "MU");
  assert.equal(flights[0]?.arrival_at, "2026-07-24T01:10:00+08:00");
  assert.deepEqual(flights[0]?.fares.map((fare) => fare.cabin_type), ["ECONOMY", "BUSINESS"]);
  assert.deepEqual(flights[0]?.fares.map((fare) => fare.price.amount_minor), [93400, 387000]);
});

test("overnight arrivals retain an explicit next-day Asia/Shanghai timestamp", () => {
  const flights = parseMuPayload(
    {
      flights: [
        {
          flightNo: "MU5001",
          originAirport: "PVG",
          destinationAirport: "TAO",
          departureTime: "23:40",
          arrivalTime: "01:10",
          fares: [{ price: 800, availability: "AVAILABLE" }],
        },
      ],
    },
    input,
  );

  assert.equal(flights[0]?.departure_at, "2026-07-23T23:40:00+08:00");
  assert.equal(flights[0]?.arrival_at, "2026-07-24T01:10:00+08:00");
});
