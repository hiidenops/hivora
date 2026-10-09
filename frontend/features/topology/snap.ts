// Magnetic alignment while dragging a card: its edges and center snap to those of the
// cards beside it (same parent). Pure: no React, no React Flow (see snap.test.mjs).

export type Box = { x: number; y: number; w: number; h: number };
/** A guide to draw: on axis "x" a vertical line at x = at (from y to y), on "y" the other way. */
export type Guide = { axis: "x" | "y"; at: number; from: number; to: number };

export const SNAP_PX = 6;

const lines = (start: number, size: number) => [start, start + size / 2, start + size];

/** How far to nudge `moving` (dx, dy) so one of its lines meets another card's within
 *  `threshold`, the closest on each axis; and the guides to show once nudged. */
export function snap(moving: Box, others: Box[], threshold = SNAP_PX): { dx: number; dy: number; guides: Guide[] } {
  const best = (axis: "x" | "y") => {
    const [pos, size] = axis === "x" ? [moving.x, moving.w] : [moving.y, moving.h];
    let shift = Infinity;
    for (const o of others) {
      const [opos, osize] = axis === "x" ? [o.x, o.w] : [o.y, o.h];
      for (const mine of lines(pos, size))
        for (const theirs of lines(opos, osize)) {
          const d = theirs - mine;
          if (Math.abs(d) <= threshold && Math.abs(d) < Math.abs(shift)) shift = d;
        }
    }
    return shift === Infinity ? 0 : shift;
  };
  const dx = best("x");
  const dy = best("y");
  const placed = { ...moving, x: moving.x + dx, y: moving.y + dy };
  const guides: Guide[] = [];
  for (const axis of ["x", "y"] as const) {
    const cross = axis === "x" ? ([placed.y, placed.y + placed.h] as const) : ([placed.x, placed.x + placed.w] as const);
    for (const at of lines(axis === "x" ? placed.x : placed.y, axis === "x" ? placed.w : placed.h)) {
      const met = others.filter((o) => lines(axis === "x" ? o.x : o.y, axis === "x" ? o.w : o.h).some((l) => Math.abs(l - at) < 0.5));
      if (!met.length) continue;
      const ends = met.flatMap((o) => (axis === "x" ? [o.y, o.y + o.h] : [o.x, o.x + o.w]));
      guides.push({ axis, at, from: Math.min(cross[0], ...ends), to: Math.max(cross[1], ...ends) });
    }
  }
  return { dx, dy, guides };
}
