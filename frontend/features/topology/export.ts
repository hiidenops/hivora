import { getViewportForBounds, type Rect } from "@xyflow/react";
import { toPng } from "html-to-image";

import type { Graph } from "./layout";

function download(name: string, href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
}

/** The drawing as a PNG: `bounds` are the nodes' (React Flow's getNodesBounds). */
export async function exportPng(bounds: Rect) {
  const viewport = document.querySelector<HTMLElement>(".react-flow__viewport");
  if (!viewport) return;
  const w = Math.ceil(bounds.width + 160);
  const h = Math.ceil(bounds.height + 160);
  const vp = getViewportForBounds(bounds, w, h, 0.5, 2, 0.05);
  const bg = getComputedStyle(document.body).backgroundColor;
  const handle = (n: HTMLElement) => n.classList?.contains("react-flow__handle");
  const url = await toPng(viewport, { backgroundColor: bg, width: w, height: h, pixelRatio: 2, filter: (n) => !handle(n), style: { width: `${w}px`, height: `${h}px`, transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})` } });
  download("hivora-topology.png", url);
}

/** The graph as the API gave it, as a JSON file. */
export function exportJson(graph: Graph) {
  download("hivora-topology.json", URL.createObjectURL(new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" })));
}
