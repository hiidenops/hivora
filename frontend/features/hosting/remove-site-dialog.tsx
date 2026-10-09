"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/input";
import type { HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useRemovalPlan, useRemoveSite } from "./hooks";
import { RestartNotice } from "./restart-notice";
import { useServerName } from "./server";

/** Lists what goes (its nginx configuration, its port) and announces the restart; its files
 *  stay unless asked (unchecked by default). */
export function RemoveSiteDialog({ appId, site, open, onOpenChange, onJob }: {
  appId: number;
  site: HostedSite;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onJob: (jobId: number) => void;
}) {
  const { t, errorMessage } = useI18n();
  const server = useServerName();
  const [removeData, setRemoveData] = useState(false);
  const plan = useRemovalPlan(appId, site.id, open);
  const remove = useRemoveSite(appId, site.id);
  const folder = `sites/${site.slug}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("hosting.removeTitle", { name: site.name })} closeLabel={t("common.close")}>
        {plan.error ? (
          <Alert tone="danger">{errorMessage(plan.error)}</Alert>
        ) : !plan.data ? (
          <p className="text-muted-foreground">{t("common.loading")}</p>
        ) : (
          <div className="grid gap-4 text-sm">
            <ul className="grid list-disc gap-1 pl-5">
              <li>{t("hosting.removeConfig", { server })}</li>
              {site.port !== null && <li>{t("hosting.removePort", { port: site.port })}</li>}
            </ul>
            <div className="grid gap-2">
              <label className="flex items-center gap-2 font-medium">
                <Switch checked={removeData} onChange={(e) => setRemoveData(e.target.checked)} />
                {t("hosting.removeData")}
              </label>
              {removeData ? (
                <Alert tone="danger">
                  {t("remove.dataWarning")} <span className="font-mono text-xs">{folder}</span>
                </Alert>
              ) : (
                <p className="text-muted-foreground">
                  {t("remove.dataKept")} <span className="font-mono text-xs">{folder}</span>. {t("hosting.dataReused")}
                </p>
              )}
            </div>
            <RestartNotice plan={plan.data} removal />
            {remove.error && <Alert tone="danger">{errorMessage(remove.error)}</Alert>}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(removeData, {
                    onSuccess: (change) => {
                      onOpenChange(false);
                      onJob((change.job ?? change.config_job).id); // the revision's job ends last
                    },
                  })
                }
              >
                {t("common.delete")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
