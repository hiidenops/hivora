"use client";

import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import { Globe, House, Router, Shield, ShieldCheck, StickyNote, Monitor } from "lucide-react";

import { AppIcon } from "@/components/app-icon";
import type { AppStatus } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";
import { cn } from "@/lib/utils";

type Port = { port: number; protocol: string; exposure: string; service: string };
const EXPOSURE = { public: "bg-danger/15 text-danger", lan: "bg-info/15 text-info", vpn: "bg-ok/15 text-ok", internal: "bg-muted text-muted-foreground" } as Record<string, string>;

const handles = (
  <>
    <Handle type="target" position={Position.Top} className="!size-2 !bg-muted-foreground" />
    <Handle type="source" position={Position.Bottom} className="!size-2 !bg-muted-foreground" />
  </>
);

export function ZoneNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { label: string | null; color: string | null; count: number; level: string; minW: number; minH: number; editable?: boolean; onResized?: (w: number, h: number) => void };
  const color = d.color ?? "var(--muted-foreground)";
  return (
    <div
      className={cn("size-full rounded-lg border-2 bg-card/40", selected && "ring-2 ring-ring")}
      style={{ borderColor: color, background: `color-mix(in oklab, ${color} 7%, transparent)` }}
    >
      {d.editable && d.level !== "zones" && (
        <NodeResizer isVisible={selected} minWidth={d.minW} minHeight={d.minH} color={color} onResizeEnd={(_, p) => d.onResized?.(p.width, p.height)} />
      )}
      {handles}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold">
        <span className="size-2 rounded-full" style={{ background: color }} />
        {d.label ?? t("topology.noZone")}
        {d.level === "zones" && <span className="ml-auto font-normal text-muted-foreground">{t("topology.apps", { n: d.count })}</span>}
      </div>
    </div>
  );
}

const DOT: Record<AppStatus, string> = { healthy: "bg-ok", starting: "bg-info animate-pulse", degraded: "bg-warn", stopped: "bg-idle", error: "bg-danger", missing: "border border-idle" };

export function AppNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { label: string; slug: string; status: AppStatus; icon_url: string | null; ports: Port[]; level: string; vpn: boolean; zoneColor?: string | null; sitePorts?: (number | null)[]; hosts?: boolean };
  const status = useLiveStatus(d.slug, d.status);
  // Published ports always show (how the app is reached); internal ones only at "all"; the
  // ports of the sites it hosts show on their own cards.
  const ports = (d.level === "all" ? d.ports : d.ports.filter((p) => p.exposure !== "internal")).filter((p) => !d.sitePorts?.includes(p.port));
  return (
    <div className={cn("rounded-md border border-l-4 bg-card px-2 py-1.5 shadow-sm", selected && "ring-2 ring-ring", status === "error" && "border-danger")} style={{ borderLeftColor: d.zoneColor ?? "var(--muted-foreground)" }}>
      {handles}
      {/* Its hosted sites hang from its bottom left, in the gutter beside them. */}
      {d.hosts && <Handle id="sites" type="source" position={Position.Bottom} style={{ left: 8 }} className="!size-1.5 !bg-primary" />}
      <div className="flex items-center gap-1.5" title={t(`status.${status}`)}>
        <AppIcon src={d.icon_url} name={d.label} className="size-5 rounded" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium">{d.label}</span>
        <span className={cn("size-2 shrink-0 rounded-full", DOT[status])} aria-label={t(`status.${status}`)} />
      </div>
      {ports.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-0.5">
          {ports.map((p) => (
            <span key={`${p.service}${p.port}${p.protocol}`} title={t(`topology.exposure.${p.exposure}` as "topology.exposure.lan")} className={cn("rounded px-1 font-mono text-[9px] leading-4", EXPOSURE[p.exposure])}>
              {p.exposure === "lan" ? "LAN " : p.exposure === "public" ? "WAN " : ""}
              {p.port}/{p.protocol}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function InternetNode({ selected }: NodeProps) {
  return (
    <div className={cn("flex items-center gap-1.5 rounded-full border-2 border-danger/60 bg-card px-3 py-1 text-xs font-semibold", selected && "ring-2 ring-ring")}>
      <Globe className="size-3.5" /> Internet
      <Handle type="source" position={Position.Bottom} className="!size-2 !bg-danger" />
      <Handle type="target" position={Position.Top} className="!size-2 !bg-danger" />
    </div>
  );
}

export function FirewallNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { agent: boolean; ufw_installed?: boolean; ufw_active?: boolean; ufw_rules?: number; fail2ban_running?: boolean; banned?: number; open?: number[]; error?: string };
  const ufw = !d.agent ? t("fw.node.unknown") : d.error ? t("fw.node.error") : !d.ufw_installed ? t("fw.node.noUfw") : d.ufw_active ? t("fw.node.ufwOn", { n: d.ufw_rules ?? 0 }) : t("fw.node.ufwOff");
  return (
    <div className={cn("w-44 rounded-md border-2 bg-card px-2 py-1 text-xs", d.ufw_active ? "border-ok" : "border-warn border-dashed", selected && "ring-2 ring-ring")}>
      <Handle type="target" position={Position.Top} className="!size-2 !bg-muted-foreground" />
      <Handle type="source" position={Position.Bottom} className="!size-2 !bg-muted-foreground" />
      <div className="flex items-center gap-1.5 font-semibold">
        <Shield className="size-3.5" /> {t("fw.node.title")}
      </div>
      <p className="text-muted-foreground">{ufw}</p>
      {d.open && <p className={d.open.length ? "text-warn" : "text-muted-foreground"}>{t("fw.node.open", { n: d.open.length, ports: d.open.slice(0, 6).join(", ") + (d.open.length > 6 ? "…" : "") })}</p>}
      {d.agent && d.fail2ban_running && <p className="text-muted-foreground">{t("fw.node.f2b", { n: d.banned ?? 0 })}</p>}
    </div>
  );
}

/** A site an nginx hosts, under it: what a reverse proxy will point at. Dimmed when off. */
export function SiteNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { label: string; port: number | null; main: boolean; enabled: boolean; server_name: string | null; zoneColor?: string | null };
  return (
    <div
      className={cn(
        "flex size-full items-center gap-1.5 rounded-md border bg-card px-2 text-xs shadow-sm",
        !d.enabled && "border-dashed opacity-60",
        selected && "ring-2 ring-ring",
      )}
      title={d.server_name ?? undefined}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !bg-primary" />
      <Handle type="source" position={Position.Right} className="!size-1.5 !bg-muted-foreground" />
      <Globe className="size-3.5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1 truncate font-medium">{d.label}</span>
      {d.main && <House aria-label={t("topology.siteMain")} className="size-3 shrink-0 text-muted-foreground"><title>{t("topology.siteMain")}</title></House>}
      {!d.enabled && <span className="text-[9px] text-muted-foreground">{t("hosting.off")}</span>}
      {d.port !== null && <span className="font-mono text-[10px] text-muted-foreground">:{d.port}</span>}
    </div>
  );
}

const ICONS = { firewall: Shield, router: Router, vpn: ShieldCheck, device: Monitor, note: StickyNote } as const;

export function DeclaredNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { kind: keyof typeof ICONS; label: string };
  const Icon = ICONS[d.kind] ?? StickyNote;
  return (
    <div className={cn("w-36 rounded-md border-2 border-dashed bg-card/80 px-2 py-1 text-xs", selected && "ring-2 ring-ring")} title={t("topology.declaredHint")}>
      {handles}
      <div className="flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 break-words">{d.label}</span>
      </div>
      <p className="text-[9px] uppercase tracking-wide text-muted-foreground">{t(`topology.kind.${d.kind}` as "topology.kind.note")}</p>
    </div>
  );
}

export const nodeTypes = { zone: ZoneNode, app: AppNode, site: SiteNode, internet: InternetNode, declared: DeclaredNode, firewall: FirewallNode };
