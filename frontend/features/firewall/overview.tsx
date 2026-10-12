"use client";

import { ArrowRight, Ban, Route as RouteIcon, ScanLine, ShieldBan, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { useBlocked } from "./blocked";
import { useHost } from "./host";
import { reachable, useListening } from "./ports";
import { useRoutes } from "./routes";
import { useStaticRoutes } from "./static-routes";

type Tone = "ok" | "warn" | "danger" | "idle";
const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  idle: "bg-idle",
};

/** One section at a glance: a colored state, a line or two, a link to its page. */
function Tile({ href, icon, title, tone, children }: { href: string; icon: ReactNode; title: string; tone: Tone; children: ReactNode }) {
  return (
    <Link href={href} className="card-interactive surface group grid content-start gap-2 rounded-lg border p-4 text-sm" aria-label={title}>
      <span className="flex items-center gap-2 font-semibold">
        {icon} {title}
        <span aria-hidden className={cn("ml-auto size-2.5 rounded-full", DOT[tone])} />
      </span>
      <span className="grid gap-0.5 text-muted-foreground">{children}</span>
      <ArrowRight className="size-4 justify-self-end text-muted-foreground transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

/** The firewall's essentials: UFW, what is exposed, blocks, bans, routes (who is connected
 *  is shown in full below them, on the same page). */
export function Overview() {
  const { t } = useI18n();
  const { state } = useHost();
  const { data: ports } = useListening();
  const { data: routes } = useRoutes();
  const { data: blocked } = useBlocked();
  const { data: statics } = useStaticRoutes();
  const s = state.data;
  if (!s) return null;

  const open = ports?.filter(reachable) ?? [];
  const bypassed = open.filter((p) => p.ufw === "bypassed").length;
  const banned = s.jails.reduce((n, j) => n + j.banned.length, 0);
  const gateway = routes?.routes.find((r) => r.dst === "default")?.gateway;

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
      <Tile href="/firewall/ports/" icon={<ShieldCheck className="size-4" />} title="UFW" tone={!s.ufw_installed ? "idle" : s.ufw_active ? "ok" : "warn"}>
        <span>{!s.ufw_installed ? t("fw.node.noUfw") : s.ufw_active ? t("fw.active") : t("fw.inactive")}</span>
        {s.ufw_installed && <span>{t("fw.node.rules", { n: s.ufw_rules.length })}</span>}
        {s.ufw_defaults && <span className="truncate text-xs">{s.ufw_defaults}</span>}
      </Tile>
      <Tile
        href="/firewall/ports/"
        icon={<ScanLine className="size-4" />}
        title={t("fw.tile.exposed")}
        tone={bypassed ? "danger" : open.length ? "warn" : "ok"}
      >
        <span>{t("fw.tile.reachable", { n: open.length })}</span>
        {bypassed > 0 && <span className="text-danger">{t("fw.tile.bypassed", { n: bypassed })}</span>}
      </Tile>
      <Tile href="/firewall/blocked/" icon={<ShieldBan className="size-4" />} title={t("fw.blocked")} tone={blocked?.length ? "ok" : "idle"}>
        <span>{t("fw.tile.blocked", { n: blocked?.length ?? 0 })}</span>
      </Tile>
      <Tile
        href="/firewall/fail2ban/"
        icon={<Ban className="size-4" />}
        title="fail2ban"
        tone={!s.fail2ban_installed ? "idle" : s.fail2ban_running ? "ok" : "warn"}
      >
        <span>{!s.fail2ban_installed ? t("fw.tile.f2bMissing") : !s.fail2ban_running ? t("fw.f2bStopped") : t("fw.node.f2b", { n: banned })}</span>
        {s.fail2ban_running && <span>{t("fw.tile.jails", { n: s.jails.length })}</span>}
      </Tile>
      <Tile href="/firewall/routes/" icon={<RouteIcon className="size-4" />} title={t("fw.tab.routes")} tone="idle">
        <span>{gateway ? t("fw.tile.gateway", { gw: gateway }) : t("fw.tile.noGateway")}</span>
        <span>{t("fw.tile.forwards", { n: routes?.forwards.length ?? 0 })}</span>
        <span>{t("fw.tile.staticRoutes", { n: statics?.length ?? 0 })}</span>
      </Tile>
    </div>
  );
}
