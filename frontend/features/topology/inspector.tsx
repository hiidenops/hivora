"use client";

import { useMutation } from "@tanstack/react-query";
import { ExternalLink, Eye, Settings2, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AppStatus } from "@/lib/api/client";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import type { Change } from "./changes";
import type { GNode, Graph, Port } from "./layout";
import { KindSelect } from "./toolbar";

/** A selected node: an app (status, ports and their exposure, VPN), a zone, the firewall,
 *  the Internet, or a declared item (its kind and label, changed or removed). */
export function Inspector({ node, graph, onClose, canEdit, onChanged, changes, onChange, openFirewall }: {
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
      {node.type === "site" && (
        <>
          <p className="text-muted-foreground">
            {t(node.main ? "topology.siteMainHelp" : "topology.siteHelp", { host: String(nodes.find((n) => n.key === node.host)?.label ?? "") })}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted-foreground">{t("topology.sitePort")}</dt>
            <dd className="font-mono">{node.port === null ? "—" : String(node.port)}</dd>
            {node.server_name ? (
              <>
                <dt className="text-muted-foreground">{t("hosting.serverName")}</dt>
                <dd className="truncate font-mono">{String(node.server_name)}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">{t("topology.siteState")}</dt>
            <dd>{t(node.enabled ? "hosting.on" : "hosting.off")}</dd>
          </dl>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" asChild>
              <Link href={`/app/site/?app=${node.app_id}&site=${node.id}`}>
                {can("operator") ? <Settings2 /> : <Eye />} {t(can("operator") ? "hosting.configure" : "hosting.view")}
              </Link>
            </Button>
            {node.url ? (
              <Button size="sm" variant="outline" asChild>
                <a href={String(node.url)} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> {t("hosting.open")}
                </a>
              </Button>
            ) : null}
          </div>
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
          <KindSelect value={kind} onChange={setKind} />
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
