import assert from "node:assert/strict";
import test from "node:test";

import { ApiRequestError, buildApiErrorMessage } from "../src/api/errors.ts";

const parseError = {
  schema_version: "1.18",
  request_id: "req_test",
  error_code: "PARSE_NEEDS_INPUT",
  message: "出行日期需要明确到具体一天。",
  user_visible_message: "出行日期需要明确到具体一天。",
  retryable: false,
  details: {
    missing_fields: ["travel_date"],
    follow_up_questions: ["这个周末你想周六还是周日出发？"]
  },
  generated_at: {
    datetime: "2026-08-16T12:00:00+08:00",
    timezone: "Asia/Shanghai",
    source_timezone: "Asia/Shanghai"
  }
};

test("API errors preserve the first concrete follow-up question", () => {
  assert.equal(
    buildApiErrorMessage(parseError),
    "出行日期需要明确到具体一天。 这个周末你想周六还是周日出发？"
  );
  const error = new ApiRequestError(parseError);
  assert.equal(error.errorCode, "PARSE_NEEDS_INPUT");
  assert.deepEqual(error.details?.missing_fields, ["travel_date"]);
});

test("API error message does not duplicate a question already included by the server", () => {
  assert.equal(
    buildApiErrorMessage({
      ...parseError,
      user_visible_message: "出行日期需要明确到具体一天。 这个周末你想周六还是周日出发？"
    }),
    "出行日期需要明确到具体一天。 这个周末你想周六还是周日出发？"
  );
});
