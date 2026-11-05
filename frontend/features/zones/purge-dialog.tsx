"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bomb } from "lucide-react";
import { useState } from "react";

import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label, Switch } from "@/components/ui/input";
import { api, type JobRef, type Zone } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Plan = components["schemas"]["PurgePlanOut"];

/** Remove the zone and everything in it: each app (its containers, files and, only when
 *  asked, its data), then the zone. Everything is listed first; the zone's name is typed to
 *  confirm. One job, followed in a pop-up. */
export function PurgeDialog({ zone }: { zone: Zone }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const track = useTrackJob();
  const [open, setOpen] = useState(false);
  const [removeData, setRemoveData] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { data: plan } = useQuery({
    queryKey: ["zone-purge", zone.slug],
    queryFn: () => api<Plan>(`/zones/${zone.slug}/purge`),
    enabled: open,
  });
  const data = plan?.apps.flatMap((a) => a.data) ?? [];
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api<JobRef>(`/zones/${zone.slug}/purge`, { method: "POST", body: { remove_data: removeData } });
      track(job.id, () => {
        void qc.invalidateQueries({ queryKey: keys.zones });
        void qc.invalidateQueries({ queryKey: keys.apps });
      });
      setOpen(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        setRemoveData(false);
        setTyped("");
        setError(null);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("zones.purge")} title={t("zones.purge")}>
          <Bomb className="text-danger" />
        </Button>
      </DialogTrigger>
      <DialogContent title={t("zones.purgeTitle", { name: zone.name })} description={t("zones.purgeHelp")} closeLabel={t("common.close")}>
        {!plan ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : (
          <div className="grid gap-4 text-sm">
            {plan.blocked.length > 0 && <Alert tone="danger">{t("zones.purgeBlocked", { apps: plan.blocked.join(", ") })}</Alert>}
            {plan.vpn && <Alert tone="warn">{t("zones.purgeVpn", { vpn: plan.vpn })}</Alert>}
            <div className="grid gap-1.5">
              <h3 className="font-medium">{t("zones.purgeApps", { n: plan.apps.length })}</h3>
              <ul className="grid max-h-56 gap-1 overflow-y-auto rounded-md border p-2">
                {plan.apps.map((a) => (
                  <li key={a.id}>
                    <span className="font-medium">{a.name}</span>
                    {a.containers.length > 0 && <span className="ml-2 font-mono text-xs text-muted-foreground">{a.containers.join(", ")}</span>}
                  </li>
                ))}
                <li className="text-muted-foreground">{t("zones.purgeZone", { name: zone.name })}</li>
              </ul>
            </div>
            {data.length > 0 && (
              <div className="grid gap-2">
                <label className="flex items-center gap-2 font-medium">
                  <Switch checked={removeData} onChange={(e) => setRemoveData(e.target.checked)} />
                  {t("remove.data")}
                </label>
                {removeData ? (
                  <Alert tone="danger">
                    {t("remove.dataWarning")}
                    <ul className="mt-1 font-mono text-xs">
                      {data.map((d) => (
                        <li key={d}>{d}</li>
                      ))}
                    </ul>
                  </Alert>
                ) : (
                  <p className="text-xs text-muted-foreground">{t("zones.purgeDataKept")}</p>
                )}
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="purge-confirm">{t("zones.purgeConfirm", { name: zone.name })}</Label>
              <Input id="purge-confirm" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
            </div>
            {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
            <div className="flex justify-end">
              <Button variant="destructive" loading={busy} disabled={busy || typed.trim() !== zone.name || plan.blocked.length > 0} onClick={run}>
                <Bomb /> {t("zones.purgeRun")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
