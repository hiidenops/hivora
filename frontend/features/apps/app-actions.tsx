"use client";

import { Play, RotateCw, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { useSession } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import type { AppStatus } from "@/lib/api/client";
import { useAppAction, useJob, type AppAction } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveJob } from "@/lib/realtime";

const RUNNING: AppStatus[] = ["healthy", "starting", "degraded"];
const DONE = ["succeeded", "failed", "cancelled", "interrupted"];

/** Start / stop / restart; hidden for read-only users. */
export function AppActions({
  id,
  status,
  compact = false,
  onJob,
}: {
  id: number;
  status: AppStatus;
  compact?: boolean;
  onJob?: (jobId: number) => void;
}) {
  const { t } = useI18n();
  const { can } = useSession();
  const action = useAppAction();
  // The job it queued: the buttons wait until it ends (not just until it is queued), so a
  // quick second click does not pile up restarts.
  const [jobId, setJobId] = useState<number | null>(null);
  const [clicked, setClicked] = useState<AppAction | null>(null);
  const live = useLiveJob(jobId);
  const { data: rest, refetch } = useJob(jobId); // an event missed (too fast, link down)
  const jobStatus = rest && DONE.includes(rest.status) ? rest.status : (live?.status ?? rest?.status ?? "queued");
  const busy = action.isPending || (jobId !== null && !DONE.includes(jobStatus));
  useEffect(() => {
    if (jobId === null || !busy) return;
    const timer = setInterval(() => void refetch(), 2000);
    return () => clearInterval(timer);
  }, [jobId, busy, refetch]);
  if (!can("operator")) return null;

  const run = (a: AppAction) => {
    setClicked(a);
    action.mutate({ id, action: a }, { onSuccess: (j) => (setJobId(j.id), onJob?.(j.id)) });
  };
  const running = RUNNING.includes(status);
  const size = compact ? "icon" : "sm";
  const items: { a: AppAction; icon: typeof Play; show: boolean }[] = [
    { a: "start", icon: Play, show: !running },
    { a: "restart", icon: RotateCw, show: running },
    { a: "stop", icon: Square, show: running },
  ];
  return (
    <div className="flex gap-1">
      {items
        .filter((i) => i.show)
        .map(({ a, icon: Icon }) => (
          <Button
            key={a}
            variant="outline"
            size={size}
            loading={busy && clicked === a}
            disabled={busy}
            onClick={() => run(a)}
            aria-label={t(`action.${a}`)}
            title={t(`action.${a}`)}
          >
            <Icon /> {!compact && t(`action.${a}`)}
          </Button>
        ))}
    </div>
  );
}
