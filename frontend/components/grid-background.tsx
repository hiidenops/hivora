"use client";

import { useEffect, useRef, useState } from "react";

const CELL = 44;
const TRAIL = 10; // cells kept lit while they fade out

/** Flat grid behind the whole UI; the cell under the pointer lights up and fades. */
export function GridBackground() {
  const [cells, setCells] = useState<{ x: number; y: number; id: number }[]>([]);
  const last = useRef("");
  const seq = useRef(0);

  useEffect(() => {
    // Listening on window: cards and sidebar sit above the grid and would hide :hover.
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const x = Math.floor(e.clientX / CELL);
      const y = Math.floor(e.clientY / CELL);
      const key = `${x}:${y}`;
      if (key === last.current) return;
      last.current = key;
      setCells((prev) => [...prev.slice(-(TRAIL - 1)), { x, y, id: seq.current++ }]);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  return (
    <svg
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 size-full [mask-image:radial-gradient(900px_circle_at_50%_35%,white,transparent)]"
    >
      <defs>
        <pattern id="hv-grid" width={CELL} height={CELL} patternUnits="userSpaceOnUse">
          <path d={`M ${CELL} 0 L 0 0 0 ${CELL}`} fill="none" className="stroke-grid" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#hv-grid)" />
      {cells.map((c) => (
        <rect
          key={c.id}
          x={c.x * CELL + 1}
          y={c.y * CELL + 1}
          width={CELL - 1}
          height={CELL - 1}
          className="grid-cell"
        />
      ))}
    </svg>
  );
}
