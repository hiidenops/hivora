"use client";

import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { order, type Dep } from "./order";
import { fetchStartup, startupKey, type Startup } from "./startup";

const COL = 240; // a step's column
const ROW = 76;
const DOT: Record<string, string> = { healthy: "bg-ok", starting: "bg-warn", degraded: "bg-warn", error: "bg-danger" };

/** An app of the zone: an arrow comes in on the left (it starts after), goes out on the right. */
function AppNode({ data }: NodeProps) {
  const d = data as { name: string; status: string; editable: boolean };
  return (
    <div className="flex w-48 items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm shadow-sm">
      <Handle type="target" position={Position.Left} isConnectable={d.editable} className="!size-2.5 !bg-primary" />
      <span aria-hidden className={cn("size-2 shrink-0 rounded-full", DOT[d.status] ?? "bg-idle")} />
      <span className="truncate font-medium">{d.name}</span>
      <Handle type="source" position={Position.Right} isConnectable={d.editable} className="!size-2.5 !bg-primary" />
    </div>
  );
}

function StepLabel({ data }: NodeProps) {
  return <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{(data as { label: string }).label}</span>;
}

const nodeTypes = { app: AppNode, step: StepLabel };

/** A zone's start order: its apps in columns, step by step, linked by arrows (A → B: B starts
 *  after A, and stops before it). Draw an arrow from an app's right edge to another's left
 *  edge, click one to remove it; the same through the check boxes under the graph (keyboard).
 *  A loop is refused at once; the columns follow each change; saved in one go. */
export function StartOrder({ slug }: { slug: string }) {
  const { t, errorMessage } = useI18n();
  const { can, advanced } = useSession();
  const editable = can("operator");
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: startupKey(slug), queryFn: () => fetchStartup(slug) });
  const [edit, setEdit] = useState<{ deps: Dep[]; timeout: number } | null>(null);
  const [loop, setLoop] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (body: { deps: Dep[]; timeout: number }) =>
      api<Startup>(`/zones/${slug}/startup`, { method: "PUT", body: { dependencies: body.deps, timeout_s: body.timeout } }),
    onSuccess: (saved) => {
      qc.setQueryData(startupKey(slug), saved);
      setEdit(null);
    },
  });
  if (!data) return null;
  if (!data.apps.length) return <p className="text-sm text-muted-foreground">{t("zones.order.empty")}</p>;

  const deps = edit?.deps ?? data.dependencies;
  const timeout = edit?.timeout ?? data.timeout_s;
  const ids = data.apps.map((a) => a.id);
  const name = (id: number) => data.apps.find((a) => a.id === id)?.name ?? String(id);
  const computed = order(ids, deps);
  const steps = "steps" in computed ? computed.steps : [ids]; // a loop never gets in: refused below
  const has = (app: number, after: number) => deps.some((d) => d.app === app && d.after === after);
  const change = (next: Dep[]) => {
    const r = order(ids, next);
    if ("loop" in r) return setLoop(t("zones.order.loop", { apps: r.loop.map(name).join(" → ") }));
    setLoop(null);
    setEdit({ deps: next, timeout });
  };
  const add = (app: number, after: number) => app !== after && !has(app, after) && change([...deps, { app, after }]);
  const remove = (app: number, after: number) => change(deps.filter((d) => !(d.app === app && d.after === after)));

  const nodes: Node[] = steps.flatMap((step, col) => [
    { id: `step-${col}`, type: "step", position: { x: col * COL, y: -34 }, data: { label: t("zones.order.step", { n: col + 1 }) }, selectable: false, draggable: false },
    ...step.map((id, row) => {
      const app = data.apps.find((a) => a.id === id)!;
      return { id: String(id), type: "app", position: { x: col * COL, y: row * ROW }, data: { name: app.name, status: app.status, editable }, draggable: false };
    }),
  ]);
  const edges: Edge[] = deps.map((d) => ({
    id: `${d.after}-${d.app}`,
    source: String(d.after),
    target: String(d.app),
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--primary)" },
    style: { stroke: "var(--primary)", strokeWidth: 1.5 },
    ariaLabel: t("zones.order.arrow", { before: name(d.after), after: name(d.app) }),
    className: editable ? "cursor-pointer" : undefined,
  }));

  return (
    <div className="grid gap-4 text-sm">
      <p className="text-muted-foreground">{t("zones.order.help")}</p>
      {loop && <Alert tone="warn">{loop}</Alert>}
      {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      <div className="h-80 rounded-lg border bg-card/40" aria-label={t("zones.order.graph")} role="figure">
        <ReactFlow
          key={JSON.stringify(steps)} // a new column: framed again (fitView runs on mount)
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          nodesDraggable={false}
          nodesConnectable={editable}
          onConnect={(c) => editable && c.source && c.target && add(Number(c.target), Number(c.source))}
          onEdgeClick={(_, e) => editable && remove(Number(e.target), Number(e.source))}
          proOptions={{ hideAttribution: true }}
        />
      </div>

      <div className="grid gap-3">
        <h3 className="font-semibold">{t("zones.order.list")}</h3>
        {data.apps.map((a) => (
          <fieldset key={a.id} className="grid gap-1">
            <legend className="font-medium">{t("zones.order.after", { name: a.name })}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {data.apps.filter((b) => b.id !== a.id).map((b) => (
                <label key={b.id} className="flex items-center gap-1.5">
                  <input type="checkbox" disabled={!editable} checked={has(a.id, b.id)} onChange={(e) => (e.target.checked ? add(a.id, b.id) : remove(a.id, b.id))} />
                  {b.name}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>

      {advanced && (
        <label className="grid max-w-sm gap-1">
          <span className="font-medium">{t("zones.order.timeout")}</span>
          <Input
            type="number"
            min={10}
            max={3600}
            disabled={!editable}
            value={timeout}
            onChange={(e) => setEdit({ deps, timeout: Number(e.target.value) })}
          />
          <span className="text-xs text-muted-foreground">{t("zones.order.timeoutHelp")}</span>
        </label>
      )}

      {editable && edit && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => save.mutate(edit)} disabled={save.isPending}>
            {t("common.save")}
          </Button>
          <Button variant="ghost" onClick={() => (setEdit(null), setLoop(null))}>
            {t("common.cancel")}
          </Button>
          <span className="text-xs text-muted-foreground">{t("zones.order.unsaved")}</span>
        </div>
      )}
    </div>
  );
}
