"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DiffView } from "@/components/diff-view";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api, type JobRef } from "@/lib/api/client";
import { invalidateAppPanels, keys } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type ComposePlan = components["schemas"]["ComposePlanOut"];

/** Hand-written compose (admin): edit, check (Compose + safety checks), apply as a revision. */
export function ComposeEditor({ appId, initial, onJob, onClose }: { appId: number; initial: string; onJob: (id: number) => void; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const [text, setText] = useState(initial);
  const [plan, setPlan] = useState<ComposePlan | null>(null);
  const check = useMutation({
    mutationFn: () => api<ComposePlan>(`/apps/${appId}/compose/plan`, { method: "POST", body: { compose_yaml: text } }),
    onSuccess: setPlan,
  });
  const apply = useMutation({
    mutationFn: () => api<JobRef>(`/apps/${appId}/compose`, { method: "PUT", body: { compose_yaml: text } }),
    onSuccess: (job) => {
      onJob(job.id);
      void qc.invalidateQueries({ queryKey: keys.app(appId) });
      invalidateAppPanels(qc, appId);
      onClose();
    },
  });
  const ready = plan && plan.problems.length === 0 && plan.conflicts.length === 0;
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">{t("compose.help")}</p>
      <textarea
        aria-label={t("compose.edit")}
        spellCheck={false}
        className="h-96 w-full resize-y rounded-md border bg-[#1c1917] p-3 font-mono text-xs leading-5 text-stone-200"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setPlan(null);
        }}
      />
      {plan && plan.problems.length > 0 && (
        <Alert tone="danger">
          <p className="font-medium">{t("compose.problems")}</p>
          <ul className="list-disc pl-5">
            {plan.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      )}
      {plan?.conflicts.map((c) => (
        <Alert key={`${c.port}/${c.protocol}`} tone="danger">
          {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
        </Alert>
      ))}
      {ready && (
        <>
          <Alert tone="info">{t("compose.ok")}</Alert>
          {plan.diff.trim() && <DiffView diff={plan.diff} />}
        </>
      )}
      {(check.error ?? apply.error) && <Alert tone="danger">{errorMessage(check.error ?? apply.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={onClose}>
          {t("compose.cancel")}
        </Button>
        <Button variant="outline" disabled={check.isPending} onClick={() => check.mutate()}>
          {t("compose.check")}
        </Button>
        <Button disabled={!ready || apply.isPending} onClick={() => apply.mutate()}>
          {t("compose.apply")}
        </Button>
      </div>
    </div>
  );
}
