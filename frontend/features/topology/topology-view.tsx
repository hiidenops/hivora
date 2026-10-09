"use client";

import "@xyflow/react/dist/style.css";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { api } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

import { applyChanges, changeKey, upsert, type Change } from "./changes";
import { connectNodes } from "./connect";
import { exportJson, exportPng } from "./export";
import { FirewallDialog } from "@/features/firewall/firewall-panel";
import { Inspector } from "./inspector";
import { toFlow, type GNode, type Graph, type Level, type Port } from "./layout";
import { nodeTypes } from "./nodes";
import { PendingPanel } from "./pending-panel";
import { Toolbar } from "./toolbar";

const MAX_DETAILED = 150;
const PENDING = "hivora.topology.pending"; // prepared changes survive refreshes

function Canvas() {
  const { t } = useI18n();
  const { can } = useSession();
  const canEdit = can("operator");
  const qc = useQueryClient();
  const { data: graph, error } = useQuery({ queryKey: keys.topology, queryFn: () => api<Graph>("/topology"), refetchInterval: 60_000 });
  const [level, setLevel] = useState<Level>("apps");
  const [selected, setSelected] = useState<string | null>(null);
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
  const refresh = () => qc.invalidateQueries({ queryKey: keys.topology });

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
    const link = connectNodes(gnode(c.source), gnode(c.target));
    if (link.kind === "changes") for (const change of link.changes) onChange(change);
    else if (link.kind === "noEffect") window.alert(t("topology.noEffect"));
    else if (link.kind === "nothingClosed") window.alert(t("topology.nothingClosed", { app: link.app }));
    else void api("/topology/edges", { method: "POST", body: { source: c.source, target: c.target, label: "" } }).then(refresh);
  };
  const apply = async () => {
    setApplying(true);
    const r = await applyChanges(changes);
    setApplying(false);
    setResult(r);
    if (!r.errors.length) setChanges([]);
    void refresh();
  };
  const node = (graph?.nodes as GNode[] | undefined)?.find((n) => n.key === selected);
  const alertText = (a: Record<string, unknown>) =>
    t(`topology.alert.${a.code}` as "topology.alert.public_port", { app: String(a.app ?? ""), ports: String(a.ports ?? ""), count: Number(a.count ?? 0) });

  return (
    <div className="grid gap-4">
      <Toolbar
        level={effective}
        tooBig={tooBig}
        onLevel={setLevel}
        canEdit={canEdit}
        pending={changes.length}
        showPending={showPending}
        onTogglePending={() => setShowPending((v) => !v)}
        applying={applying}
        onApply={() => void apply()}
        onDiscard={() => setChanges([])}
        onPng={() => void exportPng(getNodesBounds(nodes))}
        onJson={() => graph && exportJson(graph)}
        onRefresh={() => void refresh()}
      />
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
        {changes.length > 0 && showPending && <PendingPanel changes={changes} onRemove={(c) => setChanges((l) => l.filter((x) => changeKey(x) !== changeKey(c)))} />}
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
          <span className="flex items-center gap-1"><span className="inline-block w-6 border-t-2" style={{ borderColor: "var(--primary)" }} /> {t("topology.legend.site")}</span>
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
