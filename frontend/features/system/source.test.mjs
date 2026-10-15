// node --test features/system/source.test.mjs (Node strips the types of source.ts itself)
import assert from "node:assert/strict";
import { test } from "node:test";

import { sourceLink, staleFrontend } from "./source.ts";

test("a release links its tag, anything else the repository", () => {
  const repo = "https://github.com/hiidenops/hivora";
  assert.equal(sourceLink(repo, "0.1.0"), `${repo}/tree/v0.1.0`);
  assert.equal(sourceLink(`${repo}/`, "0.2.0-rc.1"), `${repo}/tree/v0.2.0-rc.1`);
  assert.equal(sourceLink(repo, "dev"), repo);
  assert.equal(sourceLink(repo, "0.1"), repo);
});

test("a page built for another server version is stale", () => {
  assert.equal(staleFrontend("0.1.0", "0.1.1"), true);
  assert.equal(staleFrontend("0.1.0", "0.1.0"), false);
  assert.equal(staleFrontend(undefined, "0.1.0"), false); // `next dev`: unknown, not stale
  assert.equal(staleFrontend("0.1.0", undefined), false); // not answered yet
});
