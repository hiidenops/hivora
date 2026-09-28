"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Download, RotateCcw, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/input";
import { units } from "@/features/activity/host-charts";
import { api, type JobRef } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type Overview = components["schemas"]["BackupsOut"];
type Schedule = components["schemas"]["ScheduleIO"];

const pad = (n: number) => String(n).padStart(2, "0");

function ScheduleForm({ appId, initial, timezone, onSaved }: { appId: number; initial: Schedule; timezone: string; onSaved: () => void }) {
  const { t, errorMessage } = useI18n();
  const [s, setS] = useState(initial);
  const set = (patch: Partial<Schedule>) => setS({ ...s, ...patch });
  const save = useMutation({
    mutationFn: () => api(`/apps/${appId}/backups/schedule`, { method: "PUT", body: s }),
    onSuccess: onSaved,
  });
  const days = [
    t("backups.day.0"), t("backups.day.1"), t("backups.day.2"), t("backups.day.3"),
    t("backups.day.4"), t("backups.day.5"), t("backups.day.6"),
  ];
  return (
    <form
      className="grid gap-3 rounded-md border bg-muted/30 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="flex items-center gap-2 text-sm font-medium">
        <Switch checked={s.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> {t("backups.auto")}
      </label>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="grid gap-1">
          {t("backups.frequency")}
          <select className="h-9 rounded-md border bg-card px-2" value={s.frequency} onChange={(e) => set({ frequency: e.target.value as Schedule["frequency"] })}>
            <option value="daily">{t("backups.daily")}</option>
            <option value="weekly">{t("backups.weekly")}</option>
            <option value="hours">{t("backups.hours")}</option>
          </select>
        </label>
        {s.frequency === "weekly" && (
          <label className="grid gap-1">
            {t("backups.weekday")}
            <select className="h-9 rounded-md border bg-card px-2" value={s.weekday} onChange={(e) => set({ weekday: Number(e.target.value) })}>
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
            <Input type="number" min={1} max={168} className="h-9 w-24" value={s.every_hours} onChange={(e) => set({ every_hours: Number(e.target.value) })} />
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
                set({ hour: h || 0, minute: m || 0 });
              }}
            />
          </label>
        )}
        <label className="grid gap-1">
          {t("backups.keep")}
          <Input type="number" min={1} max={365} className="h-9 w-24" value={s.keep} onChange={(e) => set({ keep: Number(e.target.value) })} />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={s.stop} onChange={(e) => set({ stop: e.target.checked })} /> {t("backups.stop")}
      </label>
      <Button type="submit" size="sm" variant="outline" className="justify-self-start" disabled={save.isPending}>
        <Save /> {t("common.save")}
      </Button>
      {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    </form>
  );
}

/** Backups of the app's volumes: on demand, on a schedule, restore, download. */
export function BackupsCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const key = [...keys.app(appId), "backups"];
  const [open, setOpen] = useState(false);
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Overview>(`/apps/${appId}/backups`), enabled: open, refetchInterval: 10_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const act = useMutation({
    mutationFn: (f: () => Promise<JobRef | unknown>) => f(),
    onSuccess: (res) => {
      if (res && typeof res === "object" && "id" in res) onJob((res as JobRef).id);
      void refresh();
    },
  });
  const size = units(lang).size;
  return (
    <CollapsibleCard
      storageKey="app.backups"
      className="lg:col-span-2"
      onToggle={setOpen}
      title={
        <>
          <Archive className="size-5" /> {t("backups.title")}
        </>
      }
      aside={data?.schedule.enabled && data.next_run_at && (
        <span className="text-xs text-muted-foreground">{t("backups.next", { when: new Date(data.next_run_at).toLocaleString(lang) })}</span>
      )}
    >
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {data && (
        <div className="grid gap-4">
          {data.volumes.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("backups.nothing")}</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{t("backups.help", { volumes: data.volumes.join(", ") })}</p>
              <ScheduleForm key={JSON.stringify(data.schedule)} appId={appId} initial={data.schedule} timezone={data.timezone} onSaved={refresh} />
              <Button className="justify-self-start" disabled={act.isPending} onClick={() => act.mutate(() => api<JobRef>(`/apps/${appId}/backups`, { method: "POST" }))}>
                <Archive /> {t("backups.now")}
              </Button>
            </>
          )}
          {act.error && <Alert tone="danger">{errorMessage(act.error)}</Alert>}
          {data.backups.length > 0 && (
            <ul className="divide-y rounded-lg border text-sm">
              {data.backups.map((b) => (
                <li key={b.id} className="flex flex-wrap items-center gap-3 p-3">
                  <span className="font-medium">{new Date(b.created_at).toLocaleString(lang)}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{b.scheduled ? t("backups.kindAuto") : t("backups.kindManual")}</span>
                  <span className={`text-xs ${b.status === "failed" ? "text-danger" : "text-muted-foreground"}`}>
                    {b.status === "ok" ? size(b.size) : b.status === "failed" ? t("backups.status.failed") : t("backups.status.pending")}
                  </span>
                  <span className="ml-auto flex gap-1">
                    {b.status === "ok" && (
                      <>
                        <Button size="sm" variant="ghost" asChild>
                          <a href={`/api/v1/apps/${appId}/backups/${b.id}/download`} download title={t("backups.download")} aria-label={t("backups.download")}>
                            <Download />
                          </a>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          title={t("backups.restore")}
                          aria-label={t("backups.restore")}
                          onClick={() => window.confirm(t("backups.restoreConfirm", { when: new Date(b.created_at).toLocaleString(lang) })) && act.mutate(() => api<JobRef>(`/apps/${appId}/backups/${b.id}/restore`, { method: "POST" }))}
                        >
                          <RotateCcw />
                        </Button>
                      </>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t("backups.delete")}
                      aria-label={t("backups.delete")}
                      onClick={() => window.confirm(t("backups.deleteConfirm")) && act.mutate(() => api(`/apps/${appId}/backups/${b.id}`, { method: "DELETE" }))}
                    >
                      <Trash2 className="text-danger" />
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </CollapsibleCard>
  );
}
