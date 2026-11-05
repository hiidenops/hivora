"use client";

import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider, type Connection, type Edge, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import { ExternalLink, Globe, LayoutGrid, Plus, Trash2 } from "lucide-react";
import { useMemo, useState, useSyncExternalStore, type FormEvent } from "react";

import { readPref, writePref } from "@/lib/prefs";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Dns = components["schemas"]["DnsOut"];
type DnsRecord = Dns["records"][number];
type Target = Dns["targets"][number];
// What a name is linked to, as one string: "" (nothing), "ip", "app:<id>", "port:<id>:<service>:<port>".
type Link = string;

const APP_X = 380;
const ROW_H = 26;

/** The places a name of an app can lead to: the app itself (its address, any protocol),
 *  then each web port and each hosted site (a port other than 80: through the web proxy). */
function choices(t: Target): { key: Link; label: string; port: number | null; site: boolean }[] {
  const sites = t.sites.map((s) => ({ key: `port:${t.id}:${s.service}:${s.port}`, label: s.name, port: s.port, site: true }));
  const taken = new Set(sites.map((s) => s.key));
  const ports = t.ports
    .filter((p) => p.web)
    .map((p) => ({ key: `port:${t.id}:${p.service}:${p.port}`, label: `${p.service}`, port: p.port, site: false }))
    .filter((p) => !taken.has(p.key));
  return [{ key: `app:${t.id}`, label: "", port: null, site: false }, ...sites, ...ports];
}

function linkOf(r: DnsRecord): Link {
  if (r.ip) return "ip";
  if (r.app_id == null) return "";
  return r.port != null ? `port:${r.app_id}:${r.service}:${r.port}` : `app:${r.app_id}`;
}

function bodyOf(link: Link, ip?: string) {
  if (link === "ip") return { ip };
  const [kind, id, service, port] = link.split(":");
  if (kind === "app") return { app_id: Number(id) };
  if (kind === "port") return { app_id: Number(id), service, port: Number(port) };
  return {};
}

function FqdnNode({ data }: NodeProps) {
  const { t } = useI18n();
  const d = data as { record: DnsRecord; options: { key: Link; label: string }[]; onLink: (link: Link) => void; onDelete: () => void };
  const r = d.record;
  const link = linkOf(r);
  return (
    <div className="grid w-[260px] gap-1.5 rounded-md border border-l-4 border-l-primary bg-card px-2.5 py-2 shadow-sm">
      <Handle type="source" position={Position.Right} className="!size-2.5 !bg-primary" />
      <div className="flex items-center gap-1.5">
        <Globe className="size-3.5 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium" title={r.name}>{r.name}</span>
        <button type="button" className="nodrag rounded p-0.5 text-muted-foreground hover:text-danger" aria-label={t("dns.delete", { name: r.name })} title={t("dns.delete", { name: r.name })} onClick={d.onDelete}>
          <Trash2 className="size-3.5" />
        </button>
      </div>
      {/* Linking without dragging (keyboard, touch): the same choices as the map's handles. */}
      <Select className="nodrag h-7 py-0 text-xs" aria-label={t("dns.map.linkOf", { name: r.name })} value={link} onChange={(e) => d.onLink(e.target.value)}>
        <option value="">{t("dns.map.unlinked")}</option>
        {d.options.map((o) => (
          <option key={o.key} value={o.key}>{o.label}</option>
        ))}
        <option value="ip">{r.ip ? `${t("dns.ip")} : ${r.ip}` : t("dns.map.pointIp")}</option>
      </Select>
      {r.url && (
        <a className="nodrag flex items-center gap-1 text-[11px] text-info hover:underline" href={r.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink className="size-3" /> {r.url}
          {r.via_proxy && <span className="text-muted-foreground">· {t("dns.map.viaProxy", { port: r.port ?? "" })}</span>}
        </a>
      )}
    </div>
  );
}

function TargetNode({ data }: NodeProps) {
  const { t } = useI18n();
  const d = data as { target: Target; color: string; zone: string };
  return (
    <div className="w-[300px] overflow-hidden rounded-md border border-l-4 bg-card text-xs shadow-sm" style={{ borderLeftColor: d.color }}>
      <div className="flex items-center gap-2 border-b bg-muted/40 px-2.5 py-1.5">
        <span className="min-w-0 flex-1 truncate font-medium">{d.target.name}</span>
        <span className="text-[10px] text-muted-foreground">{d.zone}</span>
      </div>
      {choices(d.target).map((c) => (
        <div key={c.key} className="relative flex h-[26px] items-center gap-2 px-2.5" title={c.port && c.port !== 80 ? t("dns.map.viaProxy", { port: c.port }) : undefined}>
          <Handle id={c.key} type="target" position={Position.Left} className="!size-2.5 !bg-muted-foreground" />
          {c.port == null ? (
            <span className="text-muted-foreground">{t("dns.map.app")}</span>
          ) : (
            <>
              <span className="truncate">{c.site ? t("dns.map.site", { name: c.label }) : t("dns.map.port", { service: c.label })}</span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">:{c.port}</span>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

const nodeTypes = { fqdn: FqdnNode, target: TargetNode };

function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}
const isDark = () => document.documentElement.classList.contains("dark");

/** The VPN's DNS as a map: its names on the left (cards), the apps of its zones on the
 *  right with each place a name can lead to (the app, a web port, a hosted site); a link
 *  drawn from a name to one of them (or chosen in the name's card) aims it there. */
export function DnsMap({ appId }: { appId: number }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const dark = useSyncExternalStore(subscribeTheme, isDark, () => false);
  const key = ["vpn-dns", appId];
  const url = `/apps/${appId}/vpn/dns`;
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Dns>(url) });
  const { data: zones } = useZones();
  const [name, setName] = useState("");
  // Cards moved by hand: kept in this browser for this VPN (auto layout for the others).
  const pref = `dnsmap.${appId}` as const;
  const [moved, setMoved] = useState<Record<string, { x: number; y: number }>>(() => {
    try {
      return JSON.parse(readPref(pref) ?? "{}") as Record<string, { x: number; y: number }>;
    } catch {
      return {};
    }
  });
  const [layoutKey, setLayoutKey] = useState(0);
  const onNodesChange = (changes: NodeChange[]) => {
    let next = moved;
    let done = false;
    for (const c of changes) {
      if (c.type === "position" && c.position) {
        next = { ...next, [c.id]: c.position };
        done ||= c.dragging === false;
      }
    }
    if (next !== moved) setMoved(next);
    if (done) writePref(pref, JSON.stringify(next));
  };
  const resetLayout = () => {
    setMoved({});
    writePref(pref, "");
    setLayoutKey((k) => k + 1);
  };
  const done = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: ["addressing"] });
  };
  const add = useMutation({ mutationFn: () => api(url, { method: "POST", body: { name } }), onSuccess: () => { setName(""); done(); } });
  const link = useMutation({ mutationFn: ({ id, body }: { id: number; body: object }) => api(`${url}/${id}`, { method: "PUT", body }), onSettled: done });
  const remove = useMutation({ mutationFn: (id: number) => api(`${url}/${id}`, { method: "DELETE" }), onSuccess: done });

  const setLink = (r: DnsRecord, next: Link) => {
    let ip: string | undefined;
    if (next === "ip") {
      ip = window.prompt(t("dns.map.ipPrompt", { name: r.name }), r.ip ?? "")?.trim();
      if (!ip) return;
    }
    link.mutate({ id: r.id, body: bodyOf(next, ip) });
  };

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    const zoneOf = new Map((zones ?? []).map((z) => [z.slug, z]));
    const options = data.targets.flatMap((tg) =>
      choices(tg).map((c) => ({
        key: c.key,
        label: c.port == null ? tg.name : `${tg.name} · ${c.label} :${c.port}`,
      })),
    );
    const nodes: Node[] = [];
    let y = 0;
    for (const tg of data.targets) {
      const z = zoneOf.get(tg.zone);
      nodes.push({ id: `t${tg.id}`, type: "target", position: { x: APP_X, y }, data: { target: tg, color: z?.color ?? "var(--muted-foreground)", zone: z?.name ?? tg.zone } });
      y += 40 + choices(tg).length * ROW_H;
    }
    data.records.forEach((r, i) => {
      nodes.push({
        id: `r${r.id}`,
        type: "fqdn",
        position: { x: 0, y: i * 120 },
        data: { record: r, options, onLink: (l: Link) => setLink(r, l), onDelete: () => remove.mutate(r.id) },
      });
    });
    const edges: Edge[] = data.records
      .filter((r) => r.app_id != null && !r.ip)
      .map((r) => ({
        id: `e${r.id}`,
        source: `r${r.id}`,
        target: `t${r.app_id}`,
        targetHandle: linkOf(r),
        label: r.port == null ? undefined : r.via_proxy ? t("dns.map.edgeProxy") : t("dns.map.edgeDirect"),
        animated: r.via_proxy,
        style: { strokeWidth: 2 },
      }));
    return { nodes: nodes.map((n) => (moved[n.id] ? { ...n, position: moved[n.id] } : n)), edges };
  }, [data, zones, t, moved]);

  const onConnect = (c: Connection) => {
    const r = data?.records.find((x) => `r${x.id}` === c.source);
    if (r && c.targetHandle) setLink(r, c.targetHandle);
  };

  if (error) return <Alert tone="danger">{errorMessage(error)}</Alert>;
  if (!data) return null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <div className="grid h-full grid-rows-[auto_1fr] gap-3">
      <div className="grid gap-2 text-sm">
        {data.enabled ? <p className="text-xs text-muted-foreground">{t("dns.server", { ip: data.server })}</p> : <Alert tone="warn">{t("dns.disabled")}</Alert>}
        <form className="flex flex-wrap items-center gap-2" onSubmit={submit}>
          <Input className="h-9 w-56 font-mono text-xs" aria-label={t("dns.name")} placeholder="actual.lan" value={name} maxLength={253} required onChange={(e) => setName(e.target.value)} />
          <Button type="submit" size="sm" className="h-9" loading={add.isPending} disabled={add.isPending}>
            <Plus /> {t("dns.map.add")}
          </Button>
          {Object.keys(moved).length > 0 && (
            <Button type="button" size="sm" variant="outline" className="h-9" onClick={resetLayout}>
              <LayoutGrid /> {t("dns.map.autoLayout")}
            </Button>
          )}
          <span className="text-xs text-muted-foreground">{t("dns.map.help")}</span>
        </form>
        {[add.error, link.error, remove.error].filter(Boolean).map((e, i) => (
          <Alert key={i} tone="danger">{errorMessage(e)}</Alert>
        ))}
        {data.targets.length === 0 && <Alert tone="info">{t("dns.map.noApp")}</Alert>}
      </div>
      <div className={cn("min-h-[420px] rounded-lg border")} aria-label={t("dns.map.title")}>
        {/* Own store: opened from the topology's inspector, it would otherwise share (and overwrite) the infra map's. */}
        <ReactFlowProvider>
        <ReactFlow
          key={`${nodes.length}-${layoutKey}`} // a card added or removed: framed again
          nodes={nodes}
          onNodesChange={onNodesChange}
          edges={edges}
          nodeTypes={nodeTypes}
          colorMode={dark ? "dark" : "light"}
          onConnect={onConnect}
          onEdgesDelete={(gone) => gone.forEach((e) => {
            const r = data.records.find((x) => `e${x.id}` === e.id);
            if (r) link.mutate({ id: r.id, body: {} });
          })}
          nodesConnectable
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
        >
          <Background gap={16} />
          <Controls showInteractive={false} />
        </ReactFlow>
        </ReactFlowProvider>
      </div>
    </div>
  );
}

