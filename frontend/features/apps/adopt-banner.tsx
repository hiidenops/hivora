"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { keys, useZones } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type Candidate = components["schemas"]["CandidateOut"];

function CandidateRow({ c, onDone }: { c: Candidate; onDone: () => void }) {
  const { t, errorMessage } = useI18n();
  const { data: zones } = useZones();
  const [name, setName] = useState(c.project);
  const [zone, setZone] = useState("");
  const adopt = useMutation({
    mutationFn: () => api(`/apps/adopt`, { method: "POST", body: { project: c.project, name, zone: zone || null } }),
    onSuccess: onDone,
  });
  return (
    <li className="grid gap-2 p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono font-medium">{c.project}</span>
        <span className="text-xs text-muted-foreground">
          {t("adopt.services", { services: c.services.join(", "), running: c.running, total: c.containers })}
        </span>
      </div>
      {c.working_dir && <p className="font-mono text-xs text-muted-foreground">{c.working_dir}</p>}
      <div className="flex flex-wrap gap-2">
        <Input aria-label={t("adopt.name")} className="h-9 w-56" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <select aria-label={t("adopt.zone")} className="h-9 rounded-md border bg-card px-2 text-sm" value={zone} onChange={(e) => setZone(e.target.value)}>
          <option value="">{t("adopt.noZone")}</option>
          {zones?.map((z) => (
            <option key={z.slug} value={z.slug}>
              {z.name}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={adopt.isPending} onClick={() => adopt.mutate()}>
          {t("adopt.button")}
        </Button>
      </div>
      {adopt.error && <Alert tone="danger">{errorMessage(adopt.error)}</Alert>}
    </li>
  );
}

/** "Compose stacks found on this server": adopt them without redeploying anything. */
export function AdoptBanner() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["apps", "discover"], queryFn: () => api<Candidate[]>("/apps/discover"), staleTime: 30_000 });
  if (!data?.length) return null;
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["apps", "discover"] });
    void qc.invalidateQueries({ queryKey: keys.apps });
  };
  return (
    <Alert tone="info" className="mb-6 flex flex-wrap items-center gap-3">
      <Boxes className="size-5 shrink-0" />
      <span className="flex-1">{t("adopt.found", { n: data.length })}</span>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {t("adopt.review")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title={t("adopt.title")} description={t("adopt.help")} closeLabel={t("common.close")} className="max-w-2xl">
          <ul className="max-h-[60vh] divide-y overflow-auto rounded-lg border">
            {data.map((c) => (
              <CandidateRow key={c.project} c={c} onDone={done} />
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </Alert>
  );
}
