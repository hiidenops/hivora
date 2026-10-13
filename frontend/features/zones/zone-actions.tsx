"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ListOrdered, Play, RotateCw, Square } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { api, type JobRef } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

import { fetchStartup } from "./startup";

// The graph (React Flow) loads when its panel opens: the Zones page stays light.
const StartOrder = dynamic(() => import("./start-order").then((m) => m.StartOrder), { ssr: false });

type Action = "start" | "stop" | "restart";

/** A zone's start, stop and restart (its apps in their order, one job), and its start order. */
export function ZoneActions({ zone, operator, hasApps }: { zone: { slug: string; name: string }; operator: boolean; hasApps: boolean }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const track = useTrackJob();
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState(false);

  const run = async (action: Action) => {
    setError(null);
    try {
      const s = await fetchStartup(zone.slug);
      const name = (id: number) => s.apps.find((a) => a.id === id)?.name ?? String(id);
      const steps = action === "stop" ? [...s.steps].reverse() : s.steps;
      const list = steps.map((step, i) => `${i + 1}. ${step.map(name).join(", ")}`).join("\n");
      if (!window.confirm(t(`zones.${action}Confirm`, { name: zone.name, order: list }))) return;
      const job = await api<JobRef>(`/zones/${zone.slug}/actions`, { method: "POST", body: { action } });
      track(job.id, () => void qc.invalidateQueries({ queryKey: keys.apps }));
    } catch (e) {
      setError(e);
    }
  };

  return (
    <>
      {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        {operator && hasApps && (
          <>
            <Button size="sm" variant="outline" onClick={() => run("start")}>
              <Play /> {t("zones.start")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => run("stop")}>
              <Square /> {t("zones.stop")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => run("restart")}>
              <RotateCw /> {t("zones.restart")}
            </Button>
          </>
        )}
        {hasApps && (
          <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
            <ListOrdered /> {t("zones.startOrder")}
          </Button>
        )}
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        {open && (
          <SheetContent title={t("zones.order.title", { name: zone.name })} icon={<ListOrdered className="size-5" />} closeLabel={t("common.close")}>
            <StartOrder slug={zone.slug} />
          </SheetContent>
        )}
      </Sheet>
    </>
  );
}
