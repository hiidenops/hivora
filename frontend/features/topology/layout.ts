import type { Edge, Node } from "@xyflow/react";

import type { components } from "@/lib/api/schema";

export type Graph = components["schemas"]["GraphOut"];
export type GNode = Record<string, unknown> & { key: string; type: string; label?: string | null; parent?: string };
export type Level = "zones" | "apps" | "all";
export type Port = { port: number; container: number; protocol: string; exposure: string; service: string; override?: string | null; default?: string | null };

export const APP_W = 170;
const APP_H = { apps: 40, all: 62 };
const GAP = 14;
const PAD = 14;
const HEADER = 32;
const COLS = 2; // apps per row inside a zone
const SITE_H = 30; // a hosted site, under its nginx
const SITE_GAP = 6;
const SITE_INDENT = 16; // the links from the nginx run in this gutter
const ZONES_PER_ROW = 3;

/**
 * Automatic layout: Internet on top, zones as boxes in rows of three, their apps
 * in two columns inside (each nginx with its hosted sites under it, the shortest column
 * filled first), declared nodes in a column on the left. Positions the user saved win
 * (apps and sites are stored relative to their zone, as React Flow does).
 */
export function toFlow(graph: Graph, level: Level, saved: Graph["positions"]): { nodes: Node[]; edges: Edge[] } {
  const nodes = graph.nodes as GNode[];
  const zones = nodes.filter((n) => n.type === "zone");
  const apps = nodes.filter((n) => n.type === "app");
  const declared = nodes.filter((n) => n.type === "declared");
  const sites = nodes.filter((n) => n.type === "site");
  const sitesOf = (a: GNode) => sites.filter((s) => s.host === a.key);
  // An app card's height: its title, then its port chips (two per line); the ports of its
  // sites show on their own cards, not on the nginx's.
  const shownPorts = (a: GNode) => {
    const own = new Set(sitesOf(a).map((s) => s.port as number | null));
    return ((a.ports as Port[] | undefined) ?? []).filter((p) => (level === "all" || p.exposure !== "internal") && !own.has(p.port));
  };
  const cardH = (a: GNode) => {
    const n = shownPorts(a).length;
    return n ? 42 + Math.ceil(n / 2) * 18 : APP_H.apps;
  };
  // Cards grow when they list ports: always at "all", published ones at "apps".
  const published = (a: GNode) => (a.ports as { exposure: string }[] | undefined)?.some((p) => p.exposure !== "internal");
  const out: Node[] = [];
  type Saved = { x: number; y: number; w?: number | null; h?: number | null };
  const at = (key: string) => saved[key] as Saved | undefined;
  const pos = (key: string, x: number, y: number) => {
    const p = at(key);
    return p ? { x: p.x, y: p.y } : { x, y };
  };

  let x = 0;
  let y = 120;
  let rowH = 0;
  zones.forEach((z, i) => {
    const children = apps.filter((a) => a.parent === z.key);
    const appH = level === "all" || children.some(published) ? APP_H.all : APP_H.apps;
    // Each app with its sites under it, in the column that is the shortest so far.
    const columns = Array.from({ length: Math.max(1, Math.min(COLS, children.length)) }, () => 0);
    const placed = children.map((a) => {
      const col = columns.indexOf(Math.min(...columns));
      const top = columns[col];
      const own = level === "zones" ? [] : sitesOf(a);
      const h = own.length ? cardH(a) : appH; // a host's sites start right under its card
      columns[col] += h + own.length * (SITE_H + SITE_GAP) + GAP;
      return { a, col, top, own, h };
    });
    const auto = {
      w: level === "zones" ? 180 : PAD * 2 + columns.length * (APP_W + GAP) - GAP,
      h: level === "zones" ? 52 : HEADER + PAD + Math.max(appH + GAP, ...columns) - GAP,
    };
    // A size the user set wins, but never smaller than the apps it holds.
    const w = level === "zones" ? auto.w : Math.max(auto.w, at(z.key)?.w ?? 0);
    const h = level === "zones" ? auto.h : Math.max(auto.h, at(z.key)?.h ?? 0);
    if (i > 0 && i % ZONES_PER_ROW === 0) {
      x = 0;
      y += rowH + 60;
      rowH = 0;
    }
    out.push({ id: z.key, type: "zone", position: pos(z.key, x, y), data: { ...z, count: children.length, level, minW: auto.w, minH: auto.h }, style: { width: w, height: h }, zIndex: -1 });
    if (level !== "zones") {
      placed.forEach(({ a, col, top, own, h }) => {
        const left = PAD + col * (APP_W + GAP);
        out.push({
          id: a.key,
          type: "app",
          parentId: z.key,
          position: pos(a.key, left, HEADER + top),
          data: { ...a, level, zoneColor: z.color, sitePorts: own.map((s) => s.port), hosts: own.length > 0 },
          style: { width: APP_W },
        });
        own.forEach((s, k) => {
          out.push({
            id: s.key,
            type: "site",
            parentId: z.key,
            position: pos(s.key, left + SITE_INDENT, HEADER + top + h + SITE_GAP + k * (SITE_H + SITE_GAP)),
            data: { ...s, zoneColor: z.color },
            style: { width: APP_W - SITE_INDENT, height: SITE_H },
          });
        });
      });
    }
    x += w + 40;
    rowH = Math.max(rowH, h);
  });
  const width = Math.max(x - 40, 300);
  out.push({ id: "internet", type: "internet", position: pos("internet", width / 2 - 50, -60), data: { label: "Internet" } });
  const fw = nodes.find((n) => n.type === "firewall");
  if (fw) out.push({ id: "firewall", type: "firewall", position: pos("firewall", width / 2 - 88, 20), data: fw });
  declared.forEach((d, i) => out.push({ id: d.key, type: "declared", position: pos(d.key, -300, 160 + i * 110), data: d }));

  const shown = new Set(out.map((n) => n.id));
  const zoneOf = new Map([...apps, ...sites].map((a) => [a.key, a.parent ?? ""]));
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
      animated: e.kind === "exposed",
      type: e.kind === "site" ? "smoothstep" : undefined, // down the gutter, then into the site
      sourceHandle: e.kind === "site" && source === e.source ? "sites" : undefined,
      // Exposed ports show on the app cards ("WAN …") and in the alerts, not on the line
      // (its middle falls under the firewall card); a site's port shows on its card.
      label: e.kind === "exposed" || e.kind === "site" ? undefined : e.label || undefined,
      data: { kind: e.kind, declaredId: e.id, port: e.label },
      style:
        e.kind === "exposed"
          ? { stroke: "var(--danger)", strokeDasharray: "6 4" }
          : e.kind === "vpn"
            ? { stroke: "var(--ok)", strokeWidth: 2 }
            : e.kind === "site"
              ? { stroke: "var(--primary)", strokeWidth: 1.5 }
            : e.kind === "host"
              ? { stroke: "var(--border)", strokeWidth: 1 }
            : { stroke: "var(--muted-foreground)", strokeDasharray: "4 4" },
      labelStyle: { fontSize: 11, fill: e.kind === "exposed" ? "var(--danger)" : "var(--foreground)" },
      labelBgStyle: { fill: "var(--card)" },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 4,
    });
  }
  return { nodes: out, edges };
}
