"use client";

import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n";

export type ScheduleValue = { frequency: "daily" | "weekly" | "hours"; hour: number; minute: number; weekday: number; every_hours: number };

const pad = (n: number) => String(n).padStart(2, "0");
const select = "h-9 rounded-md border bg-card px-2";

/** Every day / week at a local time, or every N hours (backups, scheduled tasks). */
export function ScheduleFields<T extends ScheduleValue>({ value: s, onChange, timezone }: { value: T; onChange: (patch: Partial<ScheduleValue>) => void; timezone: string }) {
  const { t } = useI18n();
  const days = [
    t("backups.day.0"), t("backups.day.1"), t("backups.day.2"), t("backups.day.3"),
    t("backups.day.4"), t("backups.day.5"), t("backups.day.6"),
  ];
  return (
    <>
      <label className="grid gap-1">
        {t("backups.frequency")}
        <select className={select} value={s.frequency} onChange={(e) => onChange({ frequency: e.target.value as ScheduleValue["frequency"] })}>
          <option value="daily">{t("backups.daily")}</option>
          <option value="weekly">{t("backups.weekly")}</option>
          <option value="hours">{t("backups.hours")}</option>
        </select>
      </label>
      {s.frequency === "weekly" && (
        <label className="grid gap-1">
          {t("backups.weekday")}
          <select className={select} value={s.weekday} onChange={(e) => onChange({ weekday: Number(e.target.value) })}>
            {days.map((d, i) => (
              <option key={i} value={i}>
                {d}
              </option>
            ))}
          </select>
        </label>
      )}
      {s.frequency === "hours" ? (
        <label className="grid gap-1">
          {t("backups.everyHours")}
          <Input type="number" min={1} max={168} className="h-9 w-24" value={s.every_hours} onChange={(e) => onChange({ every_hours: Number(e.target.value) })} />
        </label>
      ) : (
        <label className="grid gap-1">
          {t("backups.time", { tz: timezone })}
          <Input
            type="time"
            className="h-9 w-32"
            value={`${pad(s.hour)}:${pad(s.minute)}`}
            onChange={(e) => {
              const [h, m] = e.target.value.split(":").map(Number);
              onChange({ hour: h || 0, minute: m || 0 });
            }}
          />
        </label>
      )}
    </>
  );
}
