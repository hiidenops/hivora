// node --test features/system/releases.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { updateState } from "./releases.ts";

const base = { enabled: true, available: true, newer: false, latest: null, error: null };

test("what the Updates card says", () => {
  assert.equal(updateState({ ...base, newer: true, latest: {} }), "newer");
  assert.equal(updateState({ ...base, latest: {} }), "upToDate");
  assert.equal(updateState(base), "none"); // no release published yet
  assert.equal(updateState({ ...base, error: "offline" }), "unknown");
  assert.equal(updateState({ ...base, enabled: false, newer: true, latest: {} }), "off");
  assert.equal(updateState({ ...base, available: false }), "unavailable");
});
