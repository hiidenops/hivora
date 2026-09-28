"use client";

import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  getViewportForBounds,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { toPng } from "html-to-image";
import { Check, Download, FileJson, LayoutTemplate, ListChecks, Plus, Trash2, Undo2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useSession } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AppStatus } from "@/lib/api/client";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { applyChanges, changeKey, upsert, type Change } from "./changes";
import { FirewallDialog } from "@/features/firewall/firewall-panel";
import { toFlow, type GNode, type Graph, type Level } from "./layout";
import { nodeTypes } from "./nodes";

const KEY = ["apps", "topology"]; // under "apps": refreshed whenever an app changes
const MAX_DETAILED = 150;
const PENDING = "hivora.topology.pending"; // prepared changes survive refreshes
const select = "h-9 rounded-md border bg-card px-2 text-sm";

function download(name: string, href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
}

type Port = { port: number; container: number; protocol: string; exposure: string; service: string; override?: string | null; default?: string | null };

function Inspector({ node, graph, onClose, canEdit, onChanged, changes, onChange, openFirewall }: {
  node: GNode; graph: Graph; onClose: () => void; canEdit: boolean; onChanged: () => void; changes: Change[]; onChange: (c: Change) => void; openFirewall: () => void;
}) {
  const { t } = useI18n();
  const { can } = useSession();
  const [label, setLabel] = useState(String(node.label ?? ""));
  const [kind, setKind] = useState(String(node.kind ?? "note"));
  const save = useMutation({ mutationFn: () => api(`/topology/nodes/${node.id}`, { method: "PUT", body: { kind, label } }), onSuccess: onChanged });
  const remove = useMutation({
    mutationFn: () => api(`/topology/nodes/${node.id}`, { method: "DELETE" }),
    onSuccess: () => {
      onClose();
      onChanged();
    },
  });
  const nodes = graph.nodes as GNode[];
  const vpns = nodes.filter((n) => n.type === "app" && n.vpn && n.key !== node.key);
  const reached = (graph.edges as { source: string; target: string; kind: string }[])
    .filter((e) => e.kind === "vpn" && e.source === node.key)
    .map((e) => {
      const target = nodes.find((n) => n.key === e.target);
      return { target: target?.type === "app" ? `@${target.slug}` : String(target?.slug ?? ""), label: String(target?.label ?? "") };
    });
  const exposed = (graph.edges as { source: string; target: string; kind: string; label?: string }[]).filter((e) => e.kind === "exposed");
  return (
    <aside className="surface absolute right-3 top-3 z-10 grid w-72 gap-3 rounded-lg border bg-card p-4 text-sm shadow-lg">
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-semibold">{node.type === "internet" ? "Internet" : String(node.label ?? t("topology.noZone"))}</h2>
        <button onClick={onClose} aria-label={t("common.close")} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>
      {node.type === "app" && (
        <>
          <StatusBadge status={node.status as AppStatus} />
          {(node.services as string[]).length > 1 && <p className="text-xs text-muted-foreground">{t("topology.services", { services: (node.services as string[]).join(", ") })}</p>}
          {node.behind_vpn && (
            <p className="rounded bg-ok/10 px-2 py-1 text-xs text-ok">
              {t("topology.behindVpn")}
              {node.vpn_address ? ` ${t("topology.vpnAddress", { address: String(node.vpn_address) })}` : ""}
            </p>
          )}
          <ul className="grid gap-1.5 text-xs">
            {(node.ports as Port[]).map((p) => {
              const key = `${p.container}/${p.protocol}`;
              const pending = changes.find((c) => c.kind === "expose" && c.appId === node.id && c.service === p.service && c.port === key) as Extract<Change, { kind: "expose" }> | undefined;
              const current = p.exposure === "public" ? "public" : p.exposure === "lan" ? "lan" : "none";
              return (
                <li key={`${p.service}${p.port}${p.protocol}`} className="flex items-center gap-2">
                  <span className="font-mono">{p.port}/{p.protocol}</span>
                  {canEdit ? (
                    <select
                      aria-label={t("topology.exposureOf", { port: key })}
                      className="h-7 rounded border bg-card px-1 text-xs"
                      value={pending?.exposure ?? current}
                      onChange={(e) => onChange({ kind: "expose", appId: Number(node.id), app: String(node.label), service: p.service, port: key, exposure: e.target.value as "public" | "lan" | "none" | "default" })}
                    >
                      {p.override && <option value="default">{t("topology.exposure.default", { exposure: t(`topology.exposure.${p.default ?? "internal"}` as "topology.exposure.lan") })}</option>}
                      <option value="public">{t("topology.exposure.public")}</option>
                      <option value="lan">{t("topology.exposure.lan")}</option>
                      <option value="none">{t("topology.exposure.none")}</option>
                    </select>
                  ) : (
                    <span>({t(`topology.exposure.${p.exposure}` as "topology.exposure.lan")})</span>
                  )}
                </li>
              );
            })}
          </ul>
          {canEdit && !node.behind_vpn && vpns.length > 0 && (
            <div className="grid gap-1">
              <p className="text-xs text-muted-foreground">{t("topology.behindHelp")}</p>
              {vpns.map((v) => (
                <Button
                  key={v.key}
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    onChange({ kind: "reach", vpnId: Number(v.id), vpn: String(v.label), target: `@${node.slug}`, targetLabel: String(node.label), on: true });
                    for (const p of (node.ports as Port[]).filter((x) => x.exposure === "public"))
                      onChange({ kind: "expose", appId: Number(node.id), app: String(node.label), service: p.service, port: `${p.container}/${p.protocol}`, exposure: "none" });
                  }}
                >
                  {t("topology.putBehind", { vpn: String(v.label) })}
                </Button>
              ))}
            </div>
          )}
          {canEdit && Boolean(node.vpn) && reached.length > 0 && (
            <div className="grid gap-1">
              <p className="text-xs font-medium">{t("topology.reached")}</p>
              {reached.map((r) => (
                <div key={r.target} className="flex items-center justify-between gap-2 text-xs">
                  <span>{r.label}</span>
                  <Button size="sm" variant="ghost" onClick={() => onChange({ kind: "reach", vpnId: Number(node.id), vpn: String(node.label), target: r.target, targetLabel: r.label, on: false })}>
                    {t("topology.detach")}
                  </Button>
                </div>
              ))}
            </div>
          )}
          <Button size="sm" asChild>
            <Link href={`/app/?id=${node.id}`}>{t("topology.openApp")}</Link>
          </Button>
        </>
      )}
      {node.type === "zone" && (
        <>
          <p className="text-muted-foreground">{t(`topology.mode.${node.network_mode}` as "topology.mode.none")}</p>
          <p>{t("topology.apps", { n: nodes.filter((n) => n.parent === node.key).length })}</p>
          <Button size="sm" variant="outline" asChild>
            <Link href="/zones/">{t("topology.openZones")}</Link>
          </Button>
        </>
      )}
      {node.type === "firewall" && (
        <>
          <p className="text-muted-foreground">{t("fw.inspector")}</p>
          {can("admin") && (
            <Button size="sm" onClick={openFirewall}>
              {t("fw.configure")}
            </Button>
          )}
        </>
      )}
      {node.type === "internet" && (
        <>
          <p className="text-muted-foreground">{t("topology.internetHelp")}</p>
          <ul className="grid gap-1 text-xs">
            {exposed.map((e) => (
              <li key={`${e.target}${e.label}`}>
                <span className="font-mono">{e.label}</span> → {String(nodes.find((n) => n.key === e.target)?.label)}
              </li>
            ))}
          </ul>
        </>
      )}
      {node.type === "declared" && canEdit && (
        <form
          className="grid gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <select className={select} value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("topology.kind")}>
            {["firewall", "router", "vpn", "device", "note"].map((k) => (
              <option key={k} value={k}>
                {t(`topology.kind.${k}` as "topology.kind.note")}
              </option>
            ))}
          </select>
          <Input value={label} maxLength={120} required onChange={(e) => setLabel(e.target.value)} aria-label={t("topology.label")} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={save.isPending}>
              {t("common.save")}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => window.confirm(t("topology.deleteConfirm")) && remove.mutate()} aria-label={t("topology.delete")}>
              <Trash2 className="text-danger" />
            </Button>
          </div>
        </form>
      )}
    </aside>
  );
}

function Canvas() {
  const { t } = useI18n();
  const { can } = useSession();
  const canEdit = can("operator");
  const qc = useQueryClient();
  const { data: graph, error } = useQuery({ queryKey: KEY, queryFn: () => api<Graph>("/topology"), refetchInterval: 60_000 });
  const [level, setLevel] = useState<Level>("apps");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState("firewall");
  const [label, setLabel] = useState("");
  const [changes, setChangesState] = useState<Change[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(PENDING) ?? "[]") as Change[];
    } catch {
      return [];
    }
  });
  const setChanges = (next: Change[] | ((l: Change[]) => Change[])) =>
    setChangesState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      try {
        sessionStorage.setItem(PENDING, JSON.stringify(value));
      } catch {
        /* private mode: kept for this page only */
      }
      return value;
    });
  const [firewallOpen, setFirewallOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<{ jobs: number[]; errors: string[] } | null>(null);
  const { getIntersectingNodes, getNodesBounds } = useReactFlow();
  const [showPending, setShowPending] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });

  const tooBig = (graph?.nodes.length ?? 0) > MAX_DETAILED;
  const effective: Level = tooBig ? "zones" : level;
  const flow = useMemo(() => {
    if (!graph) return null;
    const f = toFlow(graph, effective, graph.positions);
    // Zone boxes: resizable by operators, their size saved with their position.
    for (const n of f.nodes) {
      if (n.type !== "zone") continue;
      n.data = {
        ...n.data,
        editable: canEdit,
        onResized: (width: number, height: number) =>
          void api("/topology/layout", { method: "PUT", body: { positions: { [n.id]: { ...n.position, w: Math.round(width), h: Math.round(height) } } } }).then(refresh),
      };
    }
    return f;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh is stable enough (query key)
  }, [graph, effective, canEdit]);
  useEffect(() => {
    if (!flow) return;
    setNodes(flow.nodes);
    setEdges(flow.edges);
  }, [flow, setNodes, setEdges]);

  const gnode = (id: string) => (graph?.nodes as GNode[] | undefined)?.find((n) => n.key === id);
  const onChange = (c: Change) => setChanges((list) => upsert(list, c));
  const dragStop = (node: Node, moved: Node[]) => {
    if (node.type === "app" && canEdit) {
      const zone = getIntersectingNodes(node).find((n) => n.type === "zone" && n.id !== node.parentId);
      const app = gnode(node.id);
      if (zone && app) {
        const z = gnode(zone.id);
        onChange({ kind: "move", appId: Number(app.id), app: String(app.label), zone: (z?.slug as string | null) ?? null, zoneLabel: String(z?.label ?? t("topology.noZone")) });
        if (flow) setNodes(flow.nodes); // it moves for real once applied
        return;
      }
    }
    savePositions(moved.length ? moved : [node]);
  };
  const savePositions = (moved: Node[]) => {
    if (!canEdit || !moved.length) return;
    const size = (n: Node) => (n.type === "zone" && n.measured ? { w: Math.round(n.measured.width ?? 0) || null, h: Math.round(n.measured.height ?? 0) || null } : {});
    const positions = Object.fromEntries(moved.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y), ...size(n) }]));
    void api("/topology/layout", { method: "PUT", body: { positions } }).then(refresh);
  };
  const connect = (c: Connection) => {
    if (!canEdit || !c.source || !c.target) return;
    const [a, b] = [gnode(c.source), gnode(c.target)];
    const vpn = a?.vpn ? a : b?.vpn ? b : null;
    const other = vpn === a ? b : a;
    // From a VPN to an app or a zone: a real change (the VPN joins its network).
    // Between the Internet and an app: open again what was closed (the template's own exposure).
    const inet = a?.type === "internet" ? b : b?.type === "internet" ? a : null;
    if (inet) {
      if (inet.type !== "app") return window.alert(t("topology.noEffect"));
      const closed = (inet.ports as Port[]).filter((p) => p.override === "none" && p.default && p.default !== "internal");
      if (!closed.length) return window.alert(t("topology.nothingClosed", { app: String(inet.label) }));
      for (const p of closed)
        onChange({ kind: "expose", appId: Number(inet.id), app: String(inet.label), service: p.service, port: `${p.container}/${p.protocol}`, exposure: "default" });
      return;
    }
    if (vpn && other && (other.type === "app" || (other.type === "zone" && other.slug))) {
      const target = other.type === "app" ? `@${other.slug}` : String(other.slug);
      onChange({ kind: "reach", vpnId: Number(vpn.id), vpn: String(vpn.label), target, targetLabel: String(other.label), on: true });
      if (other.type === "app")
        for (const p of (other.ports as Port[]).filter((x) => x.exposure === "public"))
          onChange({ kind: "expose", appId: Number(other.id), app: String(other.label), service: p.service, port: `${p.container}/${p.protocol}`, exposure: "none" });
      return;
    }
    // A drawn link only makes sense with a declared item (router, firewall, note...).
    if (a?.type !== "declared" && b?.type !== "declared") return window.alert(t("topology.noEffect"));
    void api("/topology/edges", { method: "POST", body: { source: c.source, target: c.target, label: "" } }).then(refresh);
  };
  const apply = async () => {
    setApplying(true);
    const r = await applyChanges(changes);
    setApplying(false);
    setResult(r);
    if (!r.errors.length) setChanges([]);
    void refresh();
  };
  const add = useMutation({
    mutationFn: () => api("/topology/nodes", { method: "POST", body: { kind, label } }),
    onSuccess: () => {
      setAdding(false);
      setLabel("");
      void refresh();
    },
  });

  const exportPng = async () => {
    const viewport = document.querySelector<HTMLElement>(".react-flow__viewport");
    if (!viewport) return;
    const bounds = getNodesBounds(nodes);
    const w = Math.ceil(bounds.width + 160);
    const h = Math.ceil(bounds.height + 160);
    const vp = getViewportForBounds(bounds, w, h, 0.5, 2, 0.05);
    const bg = getComputedStyle(document.body).backgroundColor;
    const handle = (n: HTMLElement) => n.classList?.contains("react-flow__handle");
    const url = await toPng(viewport, { backgroundColor: bg, width: w, height: h, pixelRatio: 2, filter: (n) => !handle(n), style: { width: `${w}px`, height: `${h}px`, transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})` } });
    download("hivora-topology.png", url);
  };
  const exportJson = () => {
    if (!graph) return;
    download("hivora-topology.json", URL.createObjectURL(new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" })));
  };

  const node = (graph?.nodes as GNode[] | undefined)?.find((n) => n.key === selected);
  const alertText = (a: Record<string, unknown>) =>
    t(`topology.alert.${a.code}` as "topology.alert.public_port", { app: String(a.app ?? ""), ports: String(a.ports ?? ""), count: Number(a.count ?? 0) });

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label={t("topology.level")} className="inline-flex rounded-md border p-0.5">
          {(["zones", "apps", "all"] as Level[]).map((l) => (
            <button
              key={l}
              role="tab"
              aria-selected={effective === l}
              disabled={tooBig && l !== "zones"}
              onClick={() => setLevel(l)}
              className={cn("rounded px-3 py-1 text-sm transition-colors disabled:opacity-40", effective === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
            >
              {t(`topology.level.${l}` as "topology.level.zones")}
            </button>
          ))}
        </div>
        {canEdit && (
          <Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)}>
            <Plus /> {t("topology.add")}
          </Button>
        )}
        <span className="ml-auto flex gap-1">
          {changes.length > 0 && (
            <span className="mr-2 flex gap-1 rounded-md border border-warn/60 bg-warn/10 p-0.5">
              <Button size="sm" variant="ghost" aria-expanded={showPending} title={t("topology.pending", { n: changes.length })} aria-label={t("topology.pending", { n: changes.length })} onClick={() => setShowPending((v) => !v)}>
                <ListChecks /> {changes.length}
              </Button>
              <Button size="sm" disabled={applying} title={t("topology.apply", { n: changes.length })} onClick={() => void apply()}>
                <Check /> {applying ? t("common.loading") : t("topology.applyShort")}
              </Button>
              <Button size="sm" variant="ghost" title={t("topology.discard")} aria-label={t("topology.discard")} onClick={() => setChanges([])}>
                <Undo2 />
              </Button>
            </span>
          )}
          {canEdit && (
            <Button size="sm" variant="ghost" title={t("topology.resetLayout")} aria-label={t("topology.resetLayout")} onClick={() => window.confirm(t("topology.resetConfirm")) && void api("/topology/layout", { method: "PUT", body: { positions: {} } }).then(refresh)}>
              <LayoutTemplate />
            </Button>
          )}
          <Button size="sm" variant="ghost" title={t("topology.png")} aria-label={t("topology.png")} onClick={() => void exportPng()}>
            <Download />
          </Button>
          <Button size="sm" variant="ghost" title={t("topology.json")} aria-label={t("topology.json")} onClick={exportJson}>
            <FileJson />
          </Button>
        </span>
      </div>
      {adding && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <select className={select} value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("topology.kind")}>
            {["firewall", "router", "vpn", "device", "note"].map((k) => (
              <option key={k} value={k}>
                {t(`topology.kind.${k}` as "topology.kind.note")}
              </option>
            ))}
          </select>
          <Input className="h-9 w-64" required maxLength={120} placeholder={t("topology.labelPlaceholder")} value={label} onChange={(e) => setLabel(e.target.value)} aria-label={t("topology.label")} />
          <Button size="sm" type="submit" disabled={add.isPending}>
            {t("topology.addButton")}
          </Button>
          <p className="w-full text-xs text-muted-foreground">{t("topology.addHelp")}</p>
        </form>
      )}
      {tooBig && <Alert tone="info">{t("topology.tooBig", { n: MAX_DETAILED })}</Alert>}
      {error && <Alert tone="danger">{String(error)}</Alert>}
      <div className="relative h-[70vh] min-h-[480px] overflow-hidden rounded-xl border bg-card/30">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={(_, n, moved) => dragStop(n, moved)}
          onNodeClick={(_, n) => setSelected(n.id)}
          onPaneClick={() => setSelected(null)}
          onConnect={connect}
          onEdgeClick={(_, e) => {
            const data = e.data as { declaredId?: number; kind?: string; port?: string } | undefined;
            if (!canEdit) return;
            if (data?.kind === "exposed") {
              const app = gnode(e.target);
              const [port, protocol] = String(data.port ?? "").split("/");
              const p = (app?.ports as Port[] | undefined)?.find((x) => String(x.port) === port && x.protocol === protocol);
              if (app && p && window.confirm(t("topology.closeConfirm", { port: `${port}/${protocol}`, app: String(app.label) })))
                onChange({ kind: "expose", appId: Number(app.id), app: String(app.label), service: p.service, port: `${p.container}/${p.protocol}`, exposure: "none" });
              return;
            }
            if (data?.kind === "vpn") {
              const [vpn, target] = [gnode(e.source), gnode(e.target)];
              if (vpn && target && window.confirm(t("topology.detachConfirm")))
                onChange({ kind: "reach", vpnId: Number(vpn.id), vpn: String(vpn.label), target: target.type === "app" ? `@${target.slug}` : String(target.slug), targetLabel: String(target.label), on: false });
              return;
            }
            if (data?.declaredId && window.confirm(t("topology.deleteLink"))) void api(`/topology/edges/${data.declaredId}`, { method: "DELETE" }).then(refresh);
          }}
          nodesDraggable={canEdit}
          nodesConnectable={canEdit}
          fitView
          fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
          minZoom={0.2}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
        {changes.length > 0 && showPending && (
          <section aria-label={t("topology.pending", { n: changes.length })} className="surface absolute left-3 top-3 z-10 grid max-h-[60%] w-80 gap-2 overflow-auto rounded-lg border p-3 text-xs shadow-lg">
            <p className="font-medium">{t("topology.pending", { n: changes.length })}</p>
            <ul className="grid gap-1">
              {changes.map((c) => (
                <li key={changeKey(c)} className="flex items-center justify-between gap-2">
                  <span>
                    {c.kind === "move"
                      ? t("topology.change.move", { app: c.app, zone: c.zoneLabel })
                      : c.kind === "expose"
                        ? t("topology.change.expose", { app: c.app, port: c.port, exposure: c.exposure === "default" ? t("topology.exposure.reopen") : t(`topology.exposure.${c.exposure}` as "topology.exposure.lan") })
                        : t(c.on ? "topology.change.reach" : "topology.change.unreach", { vpn: c.vpn, target: c.targetLabel })}
                  </span>
                  <button className="text-muted-foreground hover:text-foreground" aria-label={t("overrides.remove")} onClick={() => setChanges((l) => l.filter((x) => changeKey(x) !== changeKey(c)))}>
                    <X className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground">{t("topology.pendingHelp")}</p>
          </section>
        )}
        {node && graph && <Inspector key={node.key} node={node} graph={graph} canEdit={canEdit} changes={changes} onChange={onChange} openFirewall={() => setFirewallOpen(true)} onClose={() => setSelected(null)} onChanged={() => void refresh()} />}
        {firewallOpen && <FirewallDialog open={firewallOpen} onOpenChange={setFirewallOpen} onChanged={() => void refresh()} />}
      </div>
      {result && (
        <Alert tone={result.errors.length ? "danger" : "info"}>
          {result.errors.length ? result.errors.join(" · ") : t("topology.applied", { n: result.jobs.length })}
        </Alert>
      )}
      <div className="grid gap-2 text-sm">
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2 border-dashed" style={{ borderColor: "var(--danger)" }} /> {t("topology.legend.exposed")}</span>
          <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2" style={{ borderColor: "var(--ok)" }} /> {t("topology.legend.vpn")}</span>
          <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2 border-dashed" style={{ borderColor: "var(--muted-foreground)" }} /> {t("topology.legend.declared")}</span>
        </div>
        {graph && graph.alerts.length > 0 && (
          <ul className="grid gap-2">
            {graph.alerts.map((a, i) => (
              <li key={i}>
                <Alert tone={a.level === "danger" ? "danger" : a.level === "warn" ? "warn" : "info"} className="cursor-pointer" onClick={() => a.target && setSelected(String(a.target))}>
                  {alertText(a)}
                </Alert>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** The infrastructure as a graph: observed (Docker, read-only) and declared (drawn by you). */
export function TopologyView() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  );
}
