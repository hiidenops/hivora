"use client";

import { useEffect, useRef } from "react";

const CELL = 44;
const LIFE_MS = 700; // how long the trail lingers behind the pointer
const PEAK_ALPHA = 0.09; // at the pointer, before the CSS blur spreads it
const WIDTH = 64; // trail thickness in CSS pixels

type Point = { x: number; y: number; t: number };

/**
 * Flat grid behind the UI, with a soft golden trail that follows the pointer.
 * The trail is one continuous polyline on a canvas, faded by age and blurred by
 * CSS (GPU, every browser). It only draws while the trail is alive: nothing
 * runs when the pointer rests, and nothing at all with reduced motion.
 */
export function GridBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d");
    if (!ctx || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let gold = "#df911a";
    let points: Point[] = [];
    let raf = 0;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = innerWidth * dpr;
      canvas.height = innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = () => {
      const now = performance.now();
      points = points.filter((p) => now - p.t < LIFE_MS);
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.lineWidth = WIDTH;
      ctx.strokeStyle = gold;
      for (let i = 1; i < points.length; i++) {
        const a = points[i - 1];
        const b = points[i];
        ctx.globalAlpha = PEAK_ALPHA * (1 - (now - b.t) / LIFE_MS);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      raf = points.length > 1 ? requestAnimationFrame(draw) : 0;
    };

    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      points.push({ x: e.clientX, y: e.clientY, t: performance.now() });
      if (!raf) {
        // Read the theme colour per trail: it follows light/dark switches.
        gold = getComputedStyle(document.documentElement).getPropertyValue("--primary").trim() || gold;
        raf = requestAnimationFrame(draw);
      }
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
    };
  }, []);

  return (
    <>
      <canvas
        ref={canvasRef}
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 size-full blur-[18px]"
      />
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
      </svg>
    </>
  );
}
