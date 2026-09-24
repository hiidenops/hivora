"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/input";
import { useRemovalPlan, useRemoveApp } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** Lists what will be deleted; data removal is opt-in (unchecked by default). */
export function RemoveDialog({ id, name, onJob }: { id: number; name: string; onJob: (jobId: number) => void }) {
  const { t, errorMessage } = useI18n();
  const [open, setOpen] = useState(false);
  const [removeData, setRemoveData] = useState(false);
  const { data: plan } = useRemovalPlan(id, open);
  const remove = useRemoveApp();

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        setRemoveData(false);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Trash2 /> {t("action.remove")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("remove.title", { name })} closeLabel={t("common.close")}>
        {!plan ? (
          <p className="text-muted-foreground">{t("common.loading")}</p>
        ) : (
          <div className="grid gap-4 text-sm">
            <Section title={t("remove.containers")} items={plan.containers} empty={t("common.none")} />
            <Section title={t("remove.files")} items={plan.files} empty={t("common.none")} />
            {plan.data.length > 0 && (
              <div className="grid gap-2">
                <label className="flex items-center gap-2 font-medium">
                  <Switch checked={removeData} onChange={(e) => setRemoveData(e.target.checked)} />
                  {t("remove.data")}
                </label>
                {removeData ? (
                  <Alert tone="danger">
                    {t("remove.dataWarning")}
                    <ul className="mt-1 font-mono text-xs">{plan.data.map((d) => <li key={d}>{d}</li>)}</ul>
                  </Alert>
                ) : (
                  <p className="text-muted-foreground">
                    {t("remove.dataKept")} <span className="font-mono text-xs">{plan.data.join(", ")}</span>
                  </p>
                )}
              </div>
            )}
            {remove.error && <Alert tone="danger">{errorMessage(remove.error)}</Alert>}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(
                    { id, removeData },
                    {
                      onSuccess: (job) => {
                        setOpen(false);
                        onJob(job.id);
                      },
                    },
                  )
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

function Section({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h4 className="mb-1 font-medium">{title}</h4>
      {items.length ? (
        <ul className="grid gap-0.5 font-mono text-xs">{items.map((i) => <li key={i}>{i}</li>)}</ul>
      ) : (
        <p className="text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}
