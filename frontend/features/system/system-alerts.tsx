"use client";

import { Alert } from "@/components/ui/alert";
import type { SystemStatus } from "@/lib/api/client";
import { useHealth } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

import { staleFrontend } from "./source";

/** Above every page: a stale page after an update (everyone); for admins, how the panel is
 * exposed, when it is reachable from the Internet. */
export function SystemAlerts({ status }: { status: SystemStatus | undefined }) {
  const { t } = useI18n();
  const { data: health } = useHealth();
  const exposure = status?.checks.find((c) => c.id === "exposure")?.level;
  return (
    <>
      {staleFrontend(process.env.NEXT_PUBLIC_HIVORA_VERSION, health?.version) && (
        <Alert className="mb-4 flex flex-wrap items-center justify-between gap-2">
          {t("system.reload", { version: health?.version ?? "" })}
          <button className="font-medium underline" onClick={() => window.location.reload()}>
            {t("system.reloadNow")}
          </button>
        </Alert>
      )}
      {exposure === "error" && <Alert tone="danger" className="mb-4">{t("system.exposureError")}</Alert>}
      {exposure === "warn" && <Alert tone="warn" className="mb-4">{t("system.exposurePublic")}</Alert>}
    </>
  );
}

/** The sidebar's dot on Settings: something needs a look. */
export function needsAttention(status: SystemStatus | undefined): "warn" | "error" | null {
  if (status?.worst === "error") return "error";
  return status?.worst === "warn" ? "warn" : null;
}
