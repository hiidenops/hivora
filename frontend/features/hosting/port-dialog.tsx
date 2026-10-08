"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { ApiError, type HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useChangePort, usePlanPort } from "./hooks";
import { RestartNotice } from "./restart-notice";

type Conflict = { port: number; protocol: string; used_by: string; suggestion: number | null };

/** A port_conflict: who uses the port, and a free one to take instead. Any other error as text. */
export function PortError({ error, onUse }: { error: Error | null; onUse: (port: number) => void }) {
  const { t, errorMessage } = useI18n();
  if (!error) return null;
  if (!(error instanceof ApiError && error.code === "port_conflict")) return <Alert tone="danger">{errorMessage(error)}</Alert>;
  const conflicts = (error.details.conflicts as Conflict[] | undefined) ?? [];
  return conflicts.map((c) => (
    <Alert key={`${c.port}/${c.protocol}`} tone="danger">
      {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
      {c.suggestion !== null && (
        <Button type="button" variant="outline" size="sm" className="ml-2" onClick={() => onUse(c.suggestion!)}>
          {t("sites.useSuggested", { port: c.suggestion })}
        </Button>
      )}
    </Alert>
  ));
}

/** A site moves to another port (the main site: its app's web port): checked first (conflicts,
 *  restart notice), then moved. */
export function PortDialog({ appId, site, open, onOpenChange, onJob }: {
  appId: number;
  site: HostedSite;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onJob: (jobId: number) => void;
}) {
  const { t } = useI18n();
  const [port, setPort] = useState(String(site.port ?? ""));
  const plan = usePlanPort(appId, site.id);
  const change = useChangePort(appId, site.id);
  const changed = (v: string) => {
    setPort(v);
    plan.reset();
    change.reset();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!plan.data) {
      plan.mutate(Number(port));
      return;
    }
    change.mutate(Number(port), {
      onSuccess: (done) => {
        onOpenChange(false);
        onJob(done.config_job.id); // queued after the revision's job: the last to finish
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("hosting.portTitle", { name: site.name })} closeLabel={t("common.close")}>
        <form className="grid gap-5" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="site-port">{t("hosting.newPort")}</Label>
            <Input id="site-port" type="number" min={1} max={65535} required value={port} className="max-w-40 font-mono" onChange={(e) => changed(e.target.value)} />
            <p className="text-xs text-muted-foreground">{t("hosting.portHelp")}</p>
          </div>
          <PortError error={change.error ?? plan.error} onUse={(p) => changed(String(p))} />
          {plan.data && <RestartNotice plan={plan.data} />}
          <Button type="submit" className="justify-self-end" disabled={plan.isPending || change.isPending || !port || Number(port) === site.port}>
            {plan.data ? t("hosting.portConfirm") : t("hosting.check")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
