// node --test features/zones/order.test.mjs (Node strips the types of order.ts itself)
import assert from "node:assert/strict";
import { test } from "node:test";

import { order } from "./order.ts";

// As the server's tests: 1 PostgreSQL, 2 Redis, 3 Nextcloud (after 1 and 2), 4 Adminer
// (after 1), 5 nginx (after 3), 6 a lone app.
const APPS = [1, 2, 3, 4, 5, 6];
const DEPS = [{ app: 3, after: 1 }, { app: 3, after: 2 }, { app: 4, after: 1 }, { app: 5, after: 3 }];

test("the apps start step by step, independent ones together", () => {
  assert.deepEqual(order(APPS, DEPS), { steps: [[1, 2, 6], [3, 4], [5]] });
  assert.deepEqual(order(APPS, []), { steps: [[1, 2, 3, 4, 5, 6]] });
  assert.deepEqual(order([], []), { steps: [] });
});

test("a loop has no order: its apps are named, as the server does", () => {
  assert.deepEqual(order(APPS, [{ app: 1, after: 3 }, { app: 3, after: 1 }]), { loop: [1, 3] });
  assert.deepEqual(order(APPS, [...DEPS, { app: 1, after: 5 }]), { loop: [1, 5, 3] });
});

test("a dependency on an app outside the list is ignored", () => {
  assert.deepEqual(order([1, 2], [{ app: 2, after: 9 }]), { steps: [[1, 2]] });
});
