"use client";

import { Check, Copy, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { Card } from "@/components/ui/card";
import type { AppDetail, AppStatus } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { usePlayers } from "../games/minecraft-panel";

const TONE: Record<AppStatus, string> = {
  healthy: "bg-ok/15 text-ok ring-ok/30",
  starting: "bg-info/15 text-info ring-info/30",
  degraded: "bg-warn/15 text-warn ring-warn/30",
  stopped: "bg-idle/15 text-muted-foreground ring-idle/30",
  error: "bg-danger/15 text-danger ring-danger/30",
  missing: "bg-muted text-muted-foreground ring-border",
};
const DOT: Record<AppStatus, string> = {
  healthy: "bg-ok",
  starting: "bg-info animate-pulse",
  degraded: "bg-warn",
  stopped: "bg-idle",
  error: "bg-danger",
  missing: "border border-idle",
};

function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

function CopyAddress({ value }: { value: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="group inline-flex items-center gap-2 rounded-md border bg-muted/50 px-3 py-1.5 font-mono text-sm transition-colors hover:bg-muted"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* plain HTTP: no clipboard API, the address stays selectable */
        }
      }}
      title={t("common.copy")}
    >
      {value}
      {copied ? <Check className="size-4 text-ok" /> : <Copy className="size-4 text-muted-foreground group-hover:text-foreground" />}
    </button>
  );
}

/** Top-of-page overview: status, uptime, where to connect, players and key settings. */
export function StatusHero({ app, status }: { app: AppDetail; status: AppStatus }) {
  const { t, l } = useI18n();
  const now = useNow();
  const running = ["healthy", "starting", "degraded"].includes(status);
  const players = usePlayers(app.id, running && app.game === "minecraft");

  let uptime: string | null = null;
  if (running && app.started_at) {
    const minutes = Math.max(0, Math.floor((now - new Date(app.started_at).getTime()) / 60_000));
    const d = Math.floor(minutes / 1440);
    const h = Math.floor((minutes % 1440) / 60);
    const m = minutes % 60;
    uptime = d ? t("duration.dh", { d, h }) : h ? t("duration.hm", { h, m: String(m).padStart(2, "0") }) : t("duration.m", { m });
  }
  const address = app.access.game ?? app.access.web;

  return (
    <Card className="animate-enter overflow-hidden lg:col-span-2">
      <div className="flex flex-wrap items-center gap-5 p-5">
        <AppIcon src={app.icon_url} name={app.name} className="size-16 rounded-xl text-2xl" />
        <div className="grid min-w-0 flex-1 gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className={cn("inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ring-1", TONE[status])}>
              <span className={cn("size-2.5 rounded-full", DOT[status])} aria-hidden />
              {t(`status.${status}`)}
            </span>
            {uptime && <span className="text-sm text-muted-foreground">{t("app.since", { duration: uptime })}</span>}
            {app.drift && <span className="text-sm text-warn">⚠ {t("status.drift")}</span>}
          </div>
          {address && (
            <div className="flex flex-wrap items-center gap-3">
              {app.access.web && !app.access.game ? (
                <a href={app.access.web} target="_blank" rel="noopener noreferrer" className="font-mono text-sm underline-offset-4 hover:underline">
                  {app.access.web}
                </a>
              ) : (
                <CopyAddress value={address} />
              )}
              {players.data?.running && players.data.online !== null && (
                <span className="inline-flex items-center gap-1.5 text-sm">
                  <Users className="size-4 text-muted-foreground" />
                  {t("mc.online", { online: players.data.online, max: players.data.max ?? "?" })}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
      {(app.summary.length > 0 || app.revision) && (
        <dl className="grid grid-cols-2 gap-px border-t bg-border sm:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]">
          {app.summary.map((item) => (
            <div key={l(item.label)} className="bg-card px-5 py-3">
              <dt className="text-xs text-muted-foreground">{l(item.label)}</dt>
              <dd className="truncate font-mono text-sm">{l(item.value)}</dd>
            </div>
          ))}
          {app.revision && (
            <div className="bg-card px-5 py-3">
              <dt className="text-xs text-muted-foreground">{t("app.revision")}</dt>
              <dd className="font-mono text-sm">#{app.revision}</dd>
            </div>
          )}
        </dl>
      )}
    </Card>
  );
}
