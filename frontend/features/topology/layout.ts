import type { Edge, Node } from "@xyflow/react";

import type { components } from "@/lib/api/schema";

export type Graph = components["schemas"]["GraphOut"];
export type GNode = Record<string, unknown> & { key: string; type: string; label?: string | null; parent?: string };
export type Level = "zones" | "apps" | "all";

export const APP_W = 230;
const APP_H = { apps: 64, all: 104 };
const GAP = 24;
const PAD = 20;
const HEADER = 40;
const COLS = 2; // apps per row inside a zone
const ZONES_PER_ROW = 3;

/**
 * Automatic layout: Internet on top, zones as boxes in rows of three, their apps
 * in a two-column grid inside, declared nodes in a column on the left. Positions
 * the user saved win (apps are stored relative to their zone, as React Flow does).
 */
export function toFlow(graph: Graph, level: Level, saved: Graph["positions"]): { nodes: Node[]; edges: Edge[] } {
  const nodes = graph.nodes as GNode[];
  const zones = nodes.filter((n) => n.type === "zone");
  const apps = nodes.filter((n) => n.type === "app");
  const declared = nodes.filter((n) => n.type === "declared");
  const appH = level === "all" ? APP_H.all : APP_H.apps;
  const out: Node[] = [];
  const pos = (key: string, x: number, y: number) => (saved[key] as { x: number; y: number } | undefined) ?? { x, y };

  let x = 0;
  let y = 160;
  let rowH = 0;
  zones.forEach((z, i) => {
    const children = apps.filter((a) => a.parent === z.key);
    const rows = level === "zones" ? 0 : Math.ceil(children.length / COLS);
    const w = level === "zones" ? 220 : PAD * 2 + Math.max(1, Math.min(COLS, children.length)) * (APP_W + GAP) - GAP;
    const h = level === "zones" ? 70 : HEADER + PAD + Math.max(1, rows) * (appH + GAP);
    if (i > 0 && i % ZONES_PER_ROW === 0) {
      x = 0;
      y += rowH + 60;
      rowH = 0;
    }
    out.push({ id: z.key, type: "zone", position: pos(z.key, x, y), data: { ...z, count: children.length, level }, style: { width: w, height: h }, zIndex: -1 });
    if (level !== "zones") {
      children.forEach((a, j) => {
        out.push({
          id: a.key,
          type: "app",
          parentId: z.key,
          extent: "parent",
          position: pos(a.key, PAD + (j % COLS) * (APP_W + GAP), HEADER + Math.floor(j / COLS) * (appH + GAP)),
          data: { ...a, level },
          style: { width: APP_W },
        });
      });
    }
    x += w + 60;
    rowH = Math.max(rowH, h);
  });
  const width = Math.max(x - 60, 300);
  out.push({ id: "internet", type: "internet", position: pos("internet", width / 2 - 70, 0), data: { label: "Internet" } });
  declared.forEach((d, i) => out.push({ id: d.key, type: "declared", position: pos(d.key, -300, 160 + i * 110), data: d }));

  const shown = new Set(out.map((n) => n.id));
  const zoneOf = new Map(apps.map((a) => [a.key, a.parent ?? ""]));
  const edges: Edge[] = [];
  for (const e of graph.edges as (Record<string, unknown> & { source: string; target: string; kind: string; label?: string; id?: number })[]) {
    // At the "zones" level, an app's links attach to its zone.
    const source = shown.has(e.source) ? e.source : zoneOf.get(e.source) ?? "";
    const target = shown.has(e.target) ? e.target : zoneOf.get(e.target) ?? "";
    if (!shown.has(source) || !shown.has(target) || source === target) continue;
    const id = e.id ? `decl-edge:${e.id}` : `${e.kind}:${source}:${target}:${e.label ?? ""}`;
    if (edges.some((x) => x.id === id)) continue;
    edges.push({
      id,
      source,
      target,
      label: e.label || undefined,
      animated: e.kind === "exposed",
      data: { kind: e.kind, declaredId: e.id },
      style:
        e.kind === "exposed"
          ? { stroke: "var(--danger)", strokeDasharray: "6 4" }
          : e.kind === "vpn"
            ? { stroke: "var(--ok)", strokeWidth: 2 }
            : { stroke: "var(--muted-foreground)", strokeDasharray: "4 4" },
      labelStyle: { fontSize: 11 },
    });
  }
  return { nodes: out, edges };
}
