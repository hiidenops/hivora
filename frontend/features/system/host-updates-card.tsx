"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Power, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TotpForm } from "@/components/totp-form";
import { ApiError, api, type JobRef } from "@/lib/api/client";
import { useI18n, type MessageKey } from "@/lib/i18n";

type HostUpdates = {
  agent: boolean;
  checked_at: string | null;
  packages: { name: string; current: string; candidate: string; security: boolean }[];
  reboot: boolean;
  error: string | null;
};
type RebootPlan = { apps: { id: number; name: string; slug: string }[]; others: string[] };
const KEY = ["system-host-updates"];
const DONE = ["succeeded", "failed", "cancelled", "interrupted"];

/** A host job behind a recent TOTP (asked for when the server wants one), then followed
 *  every 3 s until it ends, Hivora's own restart included (the reboot). */
function useHostJob(path: string, onEnd: (status: string, error: string | null) => void) {
  const [totp, setTotp] = useState(false);
  const [job, setJob] = useState<number | null>(null);
  const start = useMutation({
    mutationFn: async (code?: string) => {
      if (code) await api("/system/confirm", { method: "POST", body: { code } });
      try {
        return await api<JobRef>(path, { method: "POST" });
      } catch (e) {
        if (e instanceof ApiError && e.code === "totp_required") {
          setTotp(true);
          return null;
        }
        throw e;
      }
    },
    onSuccess: (ref) => {
      if (!ref) return;
      setTotp(false);
      setJob(ref.id);
    },
  });
  useEffect(() => {
    if (job === null) return;
    const timer = window.setInterval(async () => {
      try {
        const j = await api<{ status: string; error: string | null }>(`/jobs/${job}`);
        if (DONE.includes(j.status)) {
          setJob(null);
          onEnd(j.status, j.error);
        }
      } catch {
        // Hivora restarting (the reboot)
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [job, onEnd]);
  return { start, totp, running: job !== null || start.isPending };
}

/** System → the host's packages (apt) and its reboot, through the host agent: one line of
 *  state, three separate buttons, the package list folded. */
export function HostUpdatesCard() {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: KEY, queryFn: () => api<HostUpdates>("/system/host/updates") });
  const [result, setResult] = useState<{ tone: "info" | "danger"; text: string } | null>(null);
  const [rebootOpen, setRebootOpen] = useState(false);
  const check = useMutation({
    mutationFn: () => api<HostUpdates>("/system/host/updates/check", { method: "POST" }),
    onSuccess: (fresh) => qc.setQueryData(KEY, fresh),
    onSettled: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const ended = (what: "upgrade" | "reboot") => (status: string, error: string | null) => {
    void qc.invalidateQueries({ queryKey: KEY });
    setResult(status === "succeeded" ? { tone: "info", text: t(`host.${what}Done`) } : { tone: "danger", text: t(`host.${what}Failed`, { error: error ?? status }) });
  };
  const [onUpgrade] = useState(() => ended("upgrade"));
  const [onReboot] = useState(() => ended("reboot"));
  const upgrade = useHostJob("/system/host/upgrade", onUpgrade);
  const reboot = useHostJob("/system/host/reboot", onReboot);
  const plan = useQuery({ queryKey: [...KEY, "reboot"], queryFn: () => api<RebootPlan>("/system/host/reboot"), enabled: rebootOpen });
  if (!data) return null;

  const n = data.packages.length;
  const security = data.packages.filter((p) => p.security).length;
  const busy = upgrade.running || reboot.running;
  const refusal = (e: unknown) => (e instanceof ApiError && e.code === "host_update_refused" ? t(`host.refused.${String(e.details.reason)}` as MessageKey) : e ? errorMessage(e) : null);
  const error = refusal(upgrade.start.error) ?? refusal(reboot.start.error) ?? (check.error ? errorMessage(check.error) : null);

  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>{t("host.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {!data.agent ? (
          <p className="text-muted-foreground">
            {t("host.agentOff")}{" "}
            <Link href="/firewall/" className="underline underline-offset-2">
              {t("host.agentLink")}
            </Link>
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {data.checked_at && !data.error && (
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${n ? "bg-info/15 text-info" : "bg-ok/15 text-ok"}`}>
                  {n ? t("host.packages", { n }) : t("host.upToDate")}
                </span>
              )}
              {security > 0 && <span className="rounded-full bg-warn/15 px-2 py-0.5 text-xs font-medium text-warn">{t("host.security", { n: security })}</span>}
              {data.reboot && <span className="rounded-full bg-danger/15 px-2 py-0.5 text-xs font-medium text-danger">{t("host.rebootNeeded")}</span>}
              <span className="ml-auto flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" loading={check.isPending} disabled={busy} onClick={() => check.mutate()} title={t("host.checkHelp")}>
                  <RefreshCw /> {check.isPending ? t("status.checking") : t("host.check")}
                </Button>
                <Button size="sm" loading={upgrade.running} disabled={busy || n === 0} onClick={() => window.confirm(t("host.upgradeConfirm", { n })) && upgrade.start.mutate(undefined)}>
                  <Download /> {t("host.upgrade")}
                </Button>
                <Button size="sm" variant={data.reboot ? "destructive" : "outline"} loading={reboot.running} disabled={busy} onClick={() => setRebootOpen(true)}>
                  <Power /> {t("host.reboot")}
                </Button>
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {data.error ? t("host.checkFailed", { error: data.error }) : data.checked_at ? t("host.checkedAt", { date: new Date(data.checked_at).toLocaleString(lang) }) : t("host.notChecked")}
            </p>
            {n > 0 && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">{t("host.list", { n })}</summary>
                <ul className="mt-2 grid max-h-64 gap-0.5 overflow-auto rounded-md border bg-muted p-2 font-mono text-xs">
                  {data.packages.map((p) => (
                    <li key={p.name} className="flex flex-wrap gap-x-2">
                      <span className={p.security ? "text-warn" : undefined}>{p.name}</span>
                      <span className="text-muted-foreground">
                        {p.current} → {p.candidate}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {upgrade.totp && <TotpForm pending={upgrade.start.isPending} onCode={(c) => upgrade.start.mutate(c)} />}
            {upgrade.running && !upgrade.start.isPending && <Alert role="status">{t("host.upgrading")}</Alert>}
            {reboot.running && !reboot.start.isPending && <Alert role="status">{t("host.rebooting")}</Alert>}
          </>
        )}
        {error && <Alert tone="danger">{error}</Alert>}
        {result && <Alert tone={result.tone}>{result.text}</Alert>}
      </CardContent>
      <Dialog open={rebootOpen} onOpenChange={setRebootOpen}>
        <DialogContent title={t("host.rebootTitle")} description={t("host.rebootHelp")} closeLabel={t("common.close")}>
          <div className="grid gap-3 text-sm">
            {plan.data ? (
              <>
                <div>
                  <p className="font-medium">{t("host.rebootApps", { n: plan.data.apps.length })}</p>
                  {plan.data.apps.length === 0 && <p className="text-muted-foreground">{t("host.rebootNoApp")}</p>}
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {plan.data.apps.map((a) => (
                      <li key={a.id} className="rounded bg-muted px-2 py-0.5 text-xs">{a.name}</li>
                    ))}
                  </ul>
                </div>
                {plan.data.others.length > 0 && (
                  <div>
                    <p className="font-medium">{t("host.rebootOthers", { n: plan.data.others.length })}</p>
                    <ul className="mt-1 flex flex-wrap gap-1">
                      {plan.data.others.map((name) => (
                        <li key={name} className="rounded bg-muted px-2 py-0.5 font-mono text-xs">{name}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-muted-foreground">{t("common.loading")}</p>
            )}
            {reboot.totp && <TotpForm pending={reboot.start.isPending} onCode={(c) => reboot.start.mutate(c)} />}
            <Button
              variant="destructive"
              className="justify-self-end"
              loading={reboot.start.isPending}
              disabled={!plan.data || busy}
              onClick={() => reboot.start.mutate(undefined, { onSuccess: (ref) => ref && setRebootOpen(false) })}
            >
              <Power /> {t("host.rebootNow")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
