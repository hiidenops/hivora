"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Globe, Router, Shield, ShieldCheck, StickyNote, Monitor } from "lucide-react";

import { AppIcon } from "@/components/app-icon";
import { StatusBadge } from "@/components/status-badge";
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
  const d = data as { label: string | null; color: string | null; count: number; level: string };
  const color = d.color ?? "var(--muted-foreground)";
  return (
    <div
      className={cn("size-full rounded-xl border-2 bg-card/40", selected && "ring-2 ring-ring")}
      style={{ borderColor: color, background: `color-mix(in oklab, ${color} 7%, transparent)` }}
    >
      {handles}
      <div className="flex items-center gap-2 px-3 py-2 text-sm font-semibold">
        <span className="size-2.5 rounded-full" style={{ background: color }} />
        {d.label ?? t("topology.noZone")}
        {d.level === "zones" && <span className="ml-auto text-xs font-normal text-muted-foreground">{t("topology.apps", { n: d.count })}</span>}
      </div>
    </div>
  );
}

export function AppNode({ data, selected }: NodeProps) {
  const d = data as { label: string; slug: string; status: AppStatus; icon_url: string | null; ports: Port[]; level: string; vpn: boolean };
  const status = useLiveStatus(d.slug, d.status);
  return (
    <div className={cn("surface rounded-lg border bg-card p-2 shadow-sm", selected && "ring-2 ring-ring", status === "error" && "border-danger")}>
      {handles}
      <div className="flex items-center gap-2">
        <AppIcon src={d.icon_url} name={d.label} className="size-8" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{d.label}</p>
          <StatusBadge status={status} />
        </div>
      </div>
      {d.level === "all" && d.ports.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {d.ports.map((p) => (
            <span key={`${p.service}${p.port}${p.protocol}`} className={cn("rounded px-1.5 py-0.5 font-mono text-[10px]", EXPOSURE[p.exposure])}>
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
    <div className={cn("flex items-center gap-2 rounded-full border-2 border-danger/60 bg-card px-4 py-2 text-sm font-semibold", selected && "ring-2 ring-ring")}>
      <Globe className="size-4" /> Internet
      <Handle type="source" position={Position.Bottom} className="!size-2 !bg-danger" />
      <Handle type="target" position={Position.Top} className="!size-2 !bg-danger" />
    </div>
  );
}

const ICONS = { firewall: Shield, router: Router, vpn: ShieldCheck, device: Monitor, note: StickyNote } as const;

export function DeclaredNode({ data, selected }: NodeProps) {
  const { t } = useI18n();
  const d = data as { kind: keyof typeof ICONS; label: string };
  const Icon = ICONS[d.kind] ?? StickyNote;
  return (
    <div className={cn("w-48 rounded-lg border-2 border-dashed bg-card/80 p-2 text-sm", selected && "ring-2 ring-ring")} title={t("topology.declaredHint")}>
      {handles}
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 break-words">{d.label}</span>
      </div>
      <p className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">{t(`topology.kind.${d.kind}` as "topology.kind.note")}</p>
    </div>
  );
}

export const nodeTypes = { zone: ZoneNode, app: AppNode, internet: InternetNode, declared: DeclaredNode };
