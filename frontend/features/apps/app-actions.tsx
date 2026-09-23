"use client";

import { Play, RotateCw, Square } from "lucide-react";

import { useSession } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import type { AppStatus } from "@/lib/api/client";
import { useAppAction, type AppAction } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

const RUNNING: AppStatus[] = ["healthy", "starting", "degraded"];

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
  if (!can("operator")) return null;

  const run = (a: AppAction) => action.mutate({ id, action: a }, { onSuccess: (job) => onJob?.(job.id) });
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
            disabled={action.isPending}
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
