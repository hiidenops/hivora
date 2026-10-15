"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleHelp, CircleX } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { units } from "@/features/activity/host-charts";
import { api, type SystemCheck, type SystemStatus } from "@/lib/api/client";
import { useSystemStatus } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";

const ICON = {
  ok: <CircleCheck className="size-4 shrink-0 text-ok" />,
  warn: <CircleAlert className="size-4 shrink-0 text-warn" />,
  error: <CircleX className="size-4 shrink-0 text-danger" />,
  unknown: <CircleHelp className="size-4 shrink-0 text-muted-foreground" />,
};

type Translate = ReturnType<typeof useI18n>["t"];

/** One line of facts per check, in the user's words. */
function summary(c: SystemCheck, t: Translate, lang: string): string {
  const v = c.values as Record<string, any>;
  const u = units(lang);
  const date = (iso: string | null) => (iso ? new Date(iso).toLocaleString(lang) : "—");
  switch (c.id) {
    case "version":
      return t("status.version.text", { version: v.version, schema: v.schema ?? "?" });
    case "database":
      return t(`status.database.${v.schema === "current" ? "current" : "behind"}` as MessageKey, { size: u.size(v.size + v.wal) }) +
        (v.quick_check ? ` · ${t("status.database.quick", { result: v.quick_check })}` : "");
    case "disk":
      return t("status.disk.text", { data: u.size(v.data_free), dataTotal: u.size(v.data_total), volumes: u.size(v.volumes_free), volumesTotal: u.size(v.volumes_total) });
    case "docker":
      return v.version ? t("status.docker.text", { version: v.version }) : t("status.docker.down");
    case "jobs":
      return t("status.jobs.text", { running: v.running, queued: v.queued, failed: v.failed, stuck: v.stuck });
    case "panel_backup":
      return v.last ? t("status.panel_backup.text", { date: date(v.last) }) : t("status.panel_backup.none");
    case "exposure":
      if (v.published == null) return t("status.exposure.unknown");
      return v.published.length ? t("status.exposure.text", { where: v.published.map((h: string) => h || "0.0.0.0").join(", ") }) : t("status.exposure.none");
    case "tls":
      return v.enabled === false ? t("status.tls.off") : v.expires ? t("status.tls.text", { date: date(v.expires), days: v.days }) : "—";
    case "admin_vpn":
      return t(`status.admin_vpn.${!v.initialized ? "pending" : !v.conf ? "noConf" : v.running ? "running" : "stopped"}` as MessageKey);
    default:
      return "";
  }
}

/** Settings → System health (admins): every check, and the database check on demand. */
export function StatusCard() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const { data } = useSystemStatus(true);
  const deep = useMutation({
    mutationFn: () => api<SystemStatus>("/system/status?deep=true"),
    onSuccess: (fresh) => qc.setQueryData(["system-status"], fresh),
  });
  if (!data) return null;
  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>{t("status.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-sm">
          {t("status.access")} <strong>{t(`status.access.${data.access}` as MessageKey)}</strong>
          <span className="block text-xs text-muted-foreground">{t("status.accessHint")}</span>
        </p>
        <ul className="divide-y rounded-lg border">
          {data.checks.map((c) => (
            <li key={c.id} className="flex items-start gap-3 p-3 text-sm">
              {ICON[c.level]}
              <span className="min-w-0">
                <span className="font-medium">{t(`status.${c.id}` as MessageKey)}</span>
                <span className="sr-only"> ({t(`status.level.${c.level}` as MessageKey)})</span>
                <span className="block text-muted-foreground">{summary(c, t, lang)}</span>
              </span>
            </li>
          ))}
        </ul>
        {deep.error && <Alert tone="danger">{String(deep.error)}</Alert>}
        <div>
          <Button variant="outline" size="sm" disabled={deep.isPending} onClick={() => deep.mutate()}>
            {deep.isPending ? t("status.checking") : t("status.deep")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
