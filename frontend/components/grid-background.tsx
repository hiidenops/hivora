"use client";

import { useEffect, useRef } from "react";

const CELL = 44; // grid spacing, CSS pixels
const PUSH_RADIUS = 90; // nodes closer than this to the pointer move away
const PUSH = 16; // maximum displacement of a node, CSS pixels
const EASE = 0.075; // fraction of the remaining distance covered per frame
const GLOW_RADIUS = 120; // cells whose centre is this close light up
const GLOW_ALPHA = 0.12; // cell fill at the pointer
const LINE_GLOW_ALPHA = 0.45; // grid lines turn gold near the pointer

/**
 * Flat grid behind the UI that bends away from the pointer; the cells around
 * it light up in gold. Frames are drawn only while nodes move: at rest (and
 * with reduced motion or touch) the canvas keeps a static grid.
 */
export function GridBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const animated = !matchMedia("(prefers-reduced-motion: reduce)").matches;

    let cols = 0;
    let rows = 0;
    let x = new Float32Array(0); // current node positions
    let y = new Float32Array(0);
    let mouse: { x: number; y: number } | null = null;
    let raf = 0;
    let lineColor = "";
    let gold = "";

    const readColors = () => {
      const css = getComputedStyle(document.documentElement);
      lineColor = css.getPropertyValue("--grid").trim() || "rgba(128,128,128,0.2)";
      gold = css.getPropertyValue("--primary").trim() || "#df911a";
    };

    const layout = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = innerWidth * dpr;
      canvas.height = innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(innerWidth / CELL) + 1;
      rows = Math.ceil(innerHeight / CELL) + 1;
      x = new Float32Array(cols * rows);
      y = new Float32Array(cols * rows);
      for (let i = 0; i < cols; i++)
        for (let j = 0; j < rows; j++) {
          x[i * rows + j] = i * CELL;
          y[i * rows + j] = j * CELL;
        }
    };

    /** Move every node toward its target; returns whether anything still moves. */
    const step = () => {
      let moving = false;
      for (let i = 0; i < cols; i++)
        for (let j = 0; j < rows; j++) {
          const k = i * rows + j;
          const ox = i * CELL;
          const oy = j * CELL;
          let tx = ox;
          let ty = oy;
          if (mouse) {
            const dx = ox - mouse.x;
            const dy = oy - mouse.y;
            const d = Math.hypot(dx, dy);
            if (d < PUSH_RADIUS && d > 0.01) {
              const f = (1 - d / PUSH_RADIUS) ** 2 * PUSH;
              tx += (dx / d) * f;
              ty += (dy / d) * f;
            }
          }
          x[k] += (tx - x[k]) * EASE;
          y[k] += (ty - y[k]) * EASE;
          if (Math.abs(tx - x[k]) > 0.05 || Math.abs(ty - y[k]) > 0.05) moving = true;
        }
      return moving;
    };

    const draw = () => {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      // Lit cells: quads through the (bent) corner nodes, fading with distance.
      if (mouse) {
        ctx.fillStyle = gold;
        const ci = Math.floor(mouse.x / CELL);
        const cj = Math.floor(mouse.y / CELL);
        const reach = Math.ceil(GLOW_RADIUS / CELL) + 1;
        for (let i = Math.max(0, ci - reach); i < Math.min(cols - 1, ci + reach); i++)
          for (let j = Math.max(0, cj - reach); j < Math.min(rows - 1, cj + reach); j++) {
            const d = Math.hypot((i + 0.5) * CELL - mouse.x, (j + 0.5) * CELL - mouse.y);
            if (d >= GLOW_RADIUS) continue;
            const a = i * rows + j;
            const b = (i + 1) * rows + j;
            ctx.globalAlpha = GLOW_ALPHA * (1 - d / GLOW_RADIUS) ** 2;
            ctx.beginPath();
            ctx.moveTo(x[a], y[a]);
            ctx.lineTo(x[b], y[b]);
            ctx.lineTo(x[b + 1], y[b + 1]);
            ctx.lineTo(x[a + 1], y[a + 1]);
            ctx.closePath();
            ctx.fill();
          }
      }
      // Grid lines.
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = lineColor;
      ctx.beginPath();
      for (let i = 0; i < cols; i++)
        for (let j = 0; j < rows; j++) {
          const k = i * rows + j;
          if (i + 1 < cols) {
            ctx.moveTo(x[k], y[k]);
            ctx.lineTo(x[k + rows], y[k + rows]);
          }
          if (j + 1 < rows) {
            ctx.moveTo(x[k], y[k]);
            ctx.lineTo(x[k + 1], y[k + 1]);
          }
        }
      ctx.stroke();
      // The same lines, gold, fading out around the pointer.
      if (mouse) {
        const glow = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, GLOW_RADIUS);
        glow.addColorStop(0, gold);
        glow.addColorStop(1, "transparent");
        ctx.globalAlpha = LINE_GLOW_ALPHA;
        ctx.strokeStyle = glow;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    };

    const frame = () => {
      const moving = step();
      draw();
      raf = moving ? requestAnimationFrame(frame) : 0;
    };
    const wake = () => {
      if (!raf) raf = requestAnimationFrame(frame);
    };

    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      mouse = { x: e.clientX, y: e.clientY };
      wake();
    };
    const onLeave = () => {
      mouse = null;
      wake();
    };
    const onResize = () => {
      layout();
      draw();
    };
    // Theme switches toggle a class on <html>: repaint with the new colours.
    const themeObserver = new MutationObserver(() => {
      readColors();
      draw();
    });

    readColors();
    layout();
    draw();
    window.addEventListener("resize", onResize);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    if (animated) {
      window.addEventListener("pointermove", onMove, { passive: true });
      document.documentElement.addEventListener("pointerleave", onLeave);
    }
    return () => {
      cancelAnimationFrame(raf);
      themeObserver.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 size-full [mask-image:radial-gradient(900px_circle_at_50%_35%,white,transparent)]"
    />
  );
}
