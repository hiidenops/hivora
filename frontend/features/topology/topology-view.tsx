"use client";

import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  getNodesBounds,
  getViewportForBounds,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { toPng } from "html-to-image";
import { Download, FileJson, LayoutTemplate, Plus, Trash2, X } from "lucide-react";
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

import { toFlow, type GNode, type Graph, type Level } from "./layout";
import { nodeTypes } from "./nodes";

const KEY = ["apps", "topology"]; // under "apps": refreshed whenever an app changes
const MAX_DETAILED = 150;
const select = "h-9 rounded-md border bg-card px-2 text-sm";

function download(name: string, href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
}

function Inspector({ node, graph, onClose, canEdit, onChanged }: { node: GNode; graph: Graph; onClose: () => void; canEdit: boolean; onChanged: () => void }) {
  const { t } = useI18n();
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
          <ul className="grid gap-1 font-mono text-xs">
            {(node.ports as { port: number; protocol: string; exposure: string; service: string }[]).map((p) => (
              <li key={`${p.service}${p.port}${p.protocol}`}>
                {p.port}/{p.protocol} → {p.service} ({t(`topology.exposure.${p.exposure}` as "topology.exposure.lan")})
              </li>
            ))}
          </ul>
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
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });

  const tooBig = (graph?.nodes.length ?? 0) > MAX_DETAILED;
  const effective: Level = tooBig ? "zones" : level;
  const flow = useMemo(() => (graph ? toFlow(graph, effective, graph.positions) : null), [graph, effective]);
  useEffect(() => {
    if (!flow) return;
    setNodes(flow.nodes);
    setEdges(flow.edges);
  }, [flow, setNodes, setEdges]);

  const savePositions = (moved: Node[]) => {
    if (!canEdit || !moved.length) return;
    const positions = Object.fromEntries(moved.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }]));
    void api("/topology/layout", { method: "PUT", body: { positions } }).then(refresh);
  };
  const connect = (c: Connection) => {
    if (!canEdit || !c.source || !c.target) return;
    void api("/topology/edges", { method: "POST", body: { source: c.source, target: c.target, label: "" } }).then(refresh);
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
    const vp = getViewportForBounds(bounds, w, h, 0.2, 2, 80);
    const bg = getComputedStyle(document.body).backgroundColor;
    const url = await toPng(viewport, { backgroundColor: bg, width: w, height: h, style: { width: `${w}px`, height: `${h}px`, transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})` } });
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
          onNodeDragStop={(_, n, moved) => savePositions(moved.length ? moved : [n])}
          onNodeClick={(_, n) => setSelected(n.id)}
          onPaneClick={() => setSelected(null)}
          onConnect={connect}
          onEdgeClick={(_, e) => {
            const id = (e.data as { declaredId?: number } | undefined)?.declaredId;
            if (canEdit && id && window.confirm(t("topology.deleteLink"))) void api(`/topology/edges/${id}`, { method: "DELETE" }).then(refresh);
          }}
          nodesDraggable={canEdit}
          nodesConnectable={canEdit}
          fitView
          minZoom={0.2}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!hidden md:!block" />
        </ReactFlow>
        {node && graph && <Inspector key={node.key} node={node} graph={graph} canEdit={canEdit} onClose={() => setSelected(null)} onChanged={() => void refresh()} />}
      </div>
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
