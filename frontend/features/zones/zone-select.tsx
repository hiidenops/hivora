"use client";

import { Select } from "@/components/ui/input";
import { useMoveZone, useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** Move an app to another zone: a new revision, applied by a job. */
export function ZoneSelect({ appId, zoneId, onJob }: { appId: number; zoneId: number | null; onJob: (id: number) => void }) {
  const { t } = useI18n();
  const { data: zones } = useZones();
  const move = useMoveZone(appId);
  const current = zones?.find((z) => z.id === zoneId)?.slug ?? "";
  return (
    <Select
      aria-label={t("zones.move")}
      className="h-8 w-auto text-xs"
      value={current}
      disabled={move.isPending || !zones}
      onChange={(e) =>
        window.confirm(t("zones.moveConfirm")) &&
        move.mutate(e.target.value || null, { onSuccess: (job) => onJob(job.id) })
      }
    >
      <option value="">{t("dashboard.unclassified")}</option>
      {zones?.map((z) => (
        <option key={z.slug} value={z.slug}>
          {z.name}
        </option>
      ))}
    </Select>
  );
}
