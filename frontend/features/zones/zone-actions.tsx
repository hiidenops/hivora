"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListOrdered, Play, RotateCw, Square } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { useTrackJob } from "@/components/job-toasts";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { api, type JobRef } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { fetchStartup, startupKey } from "./startup";

// The graph (React Flow) loads when its panel opens: the pages stay light.
const StartOrder = dynamic(() => import("./start-order").then((m) => m.StartOrder), { ssr: false });

type Zone = { slug: string; name: string };
export type ZoneAction = "start" | "stop" | "restart";

/** Start, stop or restart a zone's apps in their order (one job, followed in a pop-up), once
 *  confirmed with that order shown; `error` for the caller to show where it fits. */
export function useZoneActions(zone: Zone) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const track = useTrackJob();
  const [error, setError] = useState<unknown>(null);
  const run = async (action: ZoneAction) => {
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
  return { run, error };
}

const ACTIONS = [
  { action: "start", icon: Play, label: "zones.start", named: "zones.startZone" },
  { action: "stop", icon: Square, label: "zones.stop", named: "zones.stopZone" },
  { action: "restart", icon: RotateCw, label: "zones.restart", named: "zones.restartZone" },
] as const;

/** The three actions as one group of joined buttons: with their labels (a zone's card), or
 *  icons only (a zone's title on the dashboard; named in full for screen readers). */
export function ZoneActionButtons({ zone, run, compact = false }: { zone: Zone; run: (a: ZoneAction) => void; compact?: boolean }) {
  const { t } = useI18n();
  return (
    <div role="group" aria-label={t("zones.actions", { name: zone.name })} className="inline-flex shrink-0 divide-x overflow-hidden rounded-md border bg-card shadow-xs">
      {ACTIONS.map(({ action, icon: Icon, label, named }) => (
        <button
          key={action}
          type="button"
          onClick={() => run(action)}
          aria-label={compact ? t(named, { name: zone.name }) : undefined}
          title={t(named, { name: zone.name })}
          className={cn(
            "inline-flex items-center gap-1.5 font-medium text-foreground transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none [&_svg]:size-3.5",
            compact ? "h-7 px-2" : "h-8 px-3 text-xs",
            action === "stop" && "hover:text-danger",
          )}
        >
          <Icon /> {!compact && t(label)}
        </button>
      ))}
    </div>
  );
}

/** "Start order" (with its number of steps when asked): opens the zone's graph in a panel. */
export function StartOrderButton({ zone, steps = false, className }: { zone: Zone; steps?: boolean; className?: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: startupKey(zone.slug), queryFn: () => fetchStartup(zone.slug), enabled: steps });
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn("inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-muted-foreground transition-colors hover:text-foreground [&_svg]:size-4", className)}
      >
        <ListOrdered /> {t("zones.startOrder")}
        {steps && data && <span className="font-normal">· {t("zones.order.steps", { n: data.steps.length })}</span>}
      </button>
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
