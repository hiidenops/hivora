"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpCircle, History } from "lucide-react";
import { useState } from "react";

import { DiffView } from "@/components/diff-view";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/input";
import { units } from "@/features/activity/host-charts";
import { api, type JobRef } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type UpdatePlan = components["schemas"]["UpdatePlanOut"];
type Upgrade = components["schemas"]["UpgradeOut"];

/** Preview a new revision (upgrade or restore), then apply it: diff, conflicts, data reset. */
function ChangeDialog({ open, onOpenChange, title, plan, apply, onJob }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  plan: () => Promise<UpdatePlan>;
  apply: (resetData: boolean) => Promise<JobRef>;
  onJob: (id: number) => void;
}) {
  const { t, l, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const review = useQuery({ queryKey: ["change-plan", title], queryFn: plan, enabled: open, gcTime: 0, retry: false });
  const run = useMutation({
    mutationFn: () => apply(confirm),
    onSuccess: (job) => {
      onJob(job.id);
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: keys.apps });
    },
  });
  const p = review.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description={t("change.help")} closeLabel={t("common.close")} className="max-w-3xl">
        <div className="grid max-h-[70vh] gap-4 overflow-auto">
          {review.isPending && <p className="text-sm text-muted-foreground">{t("common.loading")}</p>}
          {review.error && <Alert tone="danger">{errorMessage(review.error)}</Alert>}
          {p?.conflicts.map((c) => (
            <Alert key={`${c.port}/${c.protocol}`} tone="danger">
              {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
            </Alert>
          ))}
          {p?.reset && (
            <Alert tone="danger" className="grid gap-3">
              <p className="font-medium">
                {t("edit.resetWarning", { fields: p.reset.labels.map((x) => l(x)).join(", "), size: units(lang).size(p.reset.size) })}
              </p>
              <label className="flex items-center gap-3 font-medium">
                <Switch checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                {t("edit.resetConfirm")}
              </label>
            </Alert>
          )}
          {p && (
            <div>
              <h4 className="mb-2 text-sm font-medium">{t("edit.diff", { from: p.revision - 1, to: p.revision })}</h4>
              {p.diff.trim() ? <DiffView diff={p.diff} /> : <Alert>{t("edit.noChange")}</Alert>}
            </div>
          )}
          {run.error && <Alert tone="danger">{errorMessage(run.error)}</Alert>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant={p?.reset ? "destructive" : undefined}
              disabled={!p || p.conflicts.length > 0 || run.isPending || (!!p.reset && !confirm)}
              onClick={() => run.mutate()}
            >
              {p?.reset ? t("edit.resetApply") : t("edit.apply")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** "A newer version is available" on the app page (template version, or free image digest). */
export function UpgradeBanner({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: [...keys.app(appId), "upgrade"],
    queryFn: () => api<Upgrade>(`/apps/${appId}/upgrade`),
    staleTime: 10 * 60_000,
    retry: false,
  });
  if (!data?.available) return null;
  return (
    <Alert tone="info" className="flex flex-wrap items-center gap-3 lg:col-span-2">
      <ArrowUpCircle className="size-5 shrink-0" />
      <span className="flex-1">
        {t(data.kind === "image" ? "upgrade.image" : "upgrade.template", { current: data.current, latest: data.latest })}
      </span>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("upgrade.review")}
      </Button>
      <ChangeDialog
        open={open}
        onOpenChange={setOpen}
        title={t("upgrade.title", { latest: data.latest })}
        plan={() => api<UpdatePlan>(`/apps/${appId}/upgrade/plan`, { method: "POST" })}
        apply={(reset_data) => api<JobRef>(`/apps/${appId}/upgrade`, { method: "POST", body: { reset_data } })}
        onJob={onJob}
      />
    </Alert>
  );
}

/** Go back to an earlier revision: its settings and template version, as a new revision. */
export function RestoreButton({ appId, number, onJob }: { appId: number; number: number; onJob: (id: number) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)} title={t("restore.button", { n: number })}>
        <History /> {t("restore.short")}
      </Button>
      <ChangeDialog
        open={open}
        onOpenChange={setOpen}
        title={t("restore.title", { n: number })}
        plan={() => api<UpdatePlan>(`/apps/${appId}/revisions/${number}/plan`, { method: "POST" })}
        apply={(reset_data) => api<JobRef>(`/apps/${appId}/revisions/${number}/restore`, { method: "POST", body: { reset_data } })}
        onJob={onJob}
      />
    </>
  );
}
