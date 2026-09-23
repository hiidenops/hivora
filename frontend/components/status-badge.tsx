"use client";

import type { AppStatus } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const tone: Record<AppStatus, string> = {
  healthy: "bg-ok",
  starting: "bg-info animate-pulse",
  degraded: "bg-warn",
  stopped: "bg-idle",
  error: "bg-danger",
  missing: "border border-idle bg-transparent",
};

export function StatusBadge({ status, drift = false }: { status: AppStatus; drift?: boolean }) {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium" title={drift ? t("status.drift") : undefined}>
      <span className={cn("size-2 rounded-full", tone[status])} aria-hidden />
      {t(`status.${status}`)}
      {drift && <span className="text-warn" aria-label={t("status.drift")}>⚠</span>}
    </span>
  );
}
