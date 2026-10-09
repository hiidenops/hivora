// node --test features/topology/snap.test.mjs (Node strips the types of snap.ts itself)
import assert from "node:assert/strict";
import { test } from "node:test";

import { snap } from "./snap.ts";

const card = (x, y, w = 100, h = 40) => ({ x, y, w, h });

test("snaps the closest line on each axis within the threshold", () => {
  // Top edges 4 px apart; horizontally far (its lines at 203/253/303, the other's at 0/50/100).
  const r = snap(card(203, 104), [card(0, 100)]);
  assert.equal(r.dy, -4);
  assert.equal(r.dx, 0);
});

test("snaps centers and edges, and shows a guide where they meet", () => {
  const r = snap(card(104, 300), [card(100, 0)]); // left edges 4 px apart
  assert.equal(r.dx, -4);
  assert.deepEqual(r.guides.filter((g) => g.axis === "x").map((g) => g.at), [100, 150, 200]); // left, center, right
  const g = r.guides[0];
  assert.deepEqual([g.from, g.to], [0, 340]); // from the other card's top to this one's bottom
});

test("nothing within the threshold: no nudge, no guide", () => {
  const r = snap(card(500, 500), [card(0, 0)]);
  assert.deepEqual(r, { dx: 0, dy: 0, guides: [] });
});

test("the nearest of several candidates wins", () => {
  const r = snap(card(0, 105), [card(300, 100), card(600, 103)]); // tops 5 px and 2 px away
  assert.equal(r.dy, -2);
});
