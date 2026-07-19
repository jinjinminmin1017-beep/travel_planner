import assert from "node:assert/strict";
import test from "node:test";

import { browserExecutableOptions } from "../src/browser-manager.js";

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
