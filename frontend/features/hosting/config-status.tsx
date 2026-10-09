"use client";

import { RefreshCw } from "lucide-react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { SiteHost } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useReapplyConfig } from "./hooks";

/** Whether nginx serves the sites as recorded (the host's last site_config job): its failure
 *  with nginx's words, and "apply again" (also at any time when `always`, advanced mode). */
export function ConfigStatus({ appId, host, always, onJob }: {
  appId: number;
  host: SiteHost;
  always: boolean;
  onJob: (jobId: number) => void;
}) {
  const { t, errorMessage } = useI18n();
  const server = host.server;
  const { can } = useSession();
  const reapply = useReapplyConfig(appId);
  const failed = host.config?.status === "failed";
  const applying = host.config?.status === "queued" || host.config?.status === "running";
  const again = can("operator") && !host.upgrade_required && (
    <Button size="sm" variant="outline" disabled={reapply.isPending || applying} onClick={() => reapply.mutate(undefined, { onSuccess: (job) => onJob(job.id) })}>
      <RefreshCw /> {t("hosting.reapply")}
    </Button>
  );

  return (
    <>
      {failed && (
        <Alert tone="danger" className="grid justify-items-start gap-2">
          <span>{t("hosting.configFailed", { server })}</span>
          {host.config?.error && <span className="font-mono text-xs">{host.config.error}</span>}
          {again}
        </Alert>
      )}
      {applying && <p className="text-xs text-muted-foreground">{t("hosting.configApplying", { server })}</p>}
      {always && !failed && again && <div>{again}</div>}
      {reapply.error && <Alert tone="danger">{errorMessage(reapply.error)}</Alert>}
    </>
  );
}
