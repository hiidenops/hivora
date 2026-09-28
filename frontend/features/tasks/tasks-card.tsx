"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { ScheduleFields } from "@/components/schedule-fields";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type Task = components["schemas"]["TaskOut"];
type Tasks = components["schemas"]["TasksOut"];
type TaskIn = components["schemas"]["TaskIn"];
const select = "h-9 rounded-md border bg-card px-2 text-sm";

const blank: TaskIn = { name: "", enabled: true, action: "restart", mode: "shell", service: null, command: "", frequency: "daily", hour: 4, minute: 0, weekday: 0, every_hours: 6 };

function TaskForm({ appId, initial, id, services, hasConsole, timezone, onDone }: {
  appId: number; initial: TaskIn; id?: number; services: string[]; hasConsole: boolean; timezone: string; onDone: () => void;
}) {
  const { t, errorMessage } = useI18n();
  const [v, setV] = useState<TaskIn>(initial);
  const set = (patch: Partial<TaskIn>) => setV({ ...v, ...patch });
  const save = useMutation({
    mutationFn: () => api(id ? `/apps/${appId}/tasks/${id}` : `/apps/${appId}/tasks`, { method: id ? "PUT" : "POST", body: v }),
    onSuccess: onDone,
  });
  return (
    <form
      className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1">
          {t("tasks.name")}
          <Input className="h-9 w-56" required maxLength={80} value={v.name} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <label className="grid gap-1">
          {t("tasks.action")}
          <select className={select} value={v.action} onChange={(e) => set({ action: e.target.value as TaskIn["action"] })}>
            <option value="restart">{t("tasks.action.restart")}</option>
            <option value="stop">{t("tasks.action.stop")}</option>
            <option value="start">{t("tasks.action.start")}</option>
            <option value="backup">{t("tasks.action.backup")}</option>
            <option value="command">{t("tasks.action.command")}</option>
          </select>
        </label>
        {v.action === "command" && hasConsole && (
          <label className="grid gap-1">
            {t("tasks.mode")}
            <select className={select} value={v.mode} onChange={(e) => set({ mode: e.target.value as TaskIn["mode"] })}>
              <option value="console">{t("tasks.mode.console")}</option>
              <option value="shell">{t("tasks.mode.shell")}</option>
            </select>
          </label>
        )}
        {v.action === "command" && v.mode === "shell" && services.length > 1 && (
          <label className="grid gap-1">
            {t("tasks.service")}
            <select className={select} value={v.service ?? ""} onChange={(e) => set({ service: e.target.value || null })}>
              <option value="">{t("tasks.mainService")}</option>
              {services.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {v.action === "command" && (
        <Input
          aria-label={t("tasks.command")}
          required
          maxLength={2000}
          className="h-9 font-mono text-xs"
          placeholder={v.mode === "console" ? "say Redémarrage dans 5 minutes" : "find /data/logs -mtime +7 -delete"}
          value={v.command}
          onChange={(e) => set({ command: e.target.value })}
        />
      )}
      <div className="flex flex-wrap items-end gap-3">
        <ScheduleFields value={v} onChange={set} timezone={timezone} />
        <label className="flex items-center gap-2 pb-2">
          <Switch checked={v.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> {t("tasks.enabled")}
        </label>
      </div>
      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" size="sm" disabled={save.isPending}>
          {t("common.save")}
        </Button>
      </div>
      {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    </form>
  );
}

/** Scheduled tasks of an app: a simplified cron (restart, backup, a command in a container). */
export function TasksCard({ appId }: { appId: number }) {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const key = [...keys.app(appId), "tasks"];
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const { data: listing, error } = useQuery({ queryKey: key, queryFn: () => api<Tasks>(`/apps/${appId}/tasks`), enabled: open, refetchInterval: 15_000 });
  const data: Task[] | undefined = listing?.tasks;
  const hasConsole = !!listing?.console;
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const act = useMutation({ mutationFn: (f: () => Promise<unknown>) => f(), onSuccess: refresh });
  const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(lang) : "—");
  const done = () => {
    setEditing(null);
    void refresh();
  };
  const formProps = { appId, services: listing?.services ?? [], hasConsole, timezone: listing?.timezone ?? "UTC", onDone: done };
  return (
    <CollapsibleCard
      storageKey="app.tasks"
      className="lg:col-span-2"
      onToggle={setOpen}
      title={
        <>
          <CalendarClock className="size-5" /> {t("tasks.title")}
        </>
      }
      aside={data && data.length > 0 && <span className="text-xs text-muted-foreground">{data.length}</span>}
    >
      <div className="grid gap-3">
        <p className="text-sm text-muted-foreground">{t("tasks.help")}</p>
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
        {data?.map((task) =>
          editing === task.id ? (
            <TaskForm key={task.id} {...formProps} id={task.id} initial={task} />
          ) : (
            <div key={task.id} className="grid gap-1 rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Switch
                  aria-label={t("tasks.enable", { name: task.name })}
                  checked={task.enabled}
                  onChange={(e) => {
                    const enabled = e.target.checked;
                    act.mutate(() => api(`/apps/${appId}/tasks/${task.id}`, { method: "PUT", body: { ...task, enabled } }));
                  }}
                />
                <span className="font-medium">{task.name}</span>
                <span className="text-xs text-muted-foreground">
                  {t(`tasks.action.${task.action}` as "tasks.action.restart")}
                  {task.action === "command" && <code className="ml-1 font-mono">{task.command}</code>}
                </span>
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" title={t("tasks.runNow")} aria-label={t("tasks.runNow")} disabled={act.isPending} onClick={() => act.mutate(() => api(`/apps/${appId}/tasks/${task.id}/run`, { method: "POST" }))}>
                    <Play />
                  </Button>
                  <Button size="sm" variant="ghost" title={t("tasks.edit")} aria-label={t("tasks.edit")} onClick={() => setEditing(task.id)}>
                    <Pencil />
                  </Button>
                  <Button size="sm" variant="ghost" title={t("tasks.delete")} aria-label={t("tasks.delete")} onClick={() => window.confirm(t("tasks.deleteConfirm", { name: task.name })) && act.mutate(() => api(`/apps/${appId}/tasks/${task.id}`, { method: "DELETE" }))}>
                    <Trash2 className="text-danger" />
                  </Button>
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("tasks.next", { when: task.enabled ? when(task.next_run_at) : t("tasks.off") })}
                {task.last_run_at && (
                  <>
                    {" · "}
                    {t("tasks.last", { when: when(task.last_run_at) })}{" "}
                    <span className={task.last_status === "failed" ? "text-danger" : task.last_status === "ok" ? "text-ok" : ""}>
                      {t(`tasks.status.${task.last_status ?? "queued"}` as "tasks.status.ok")}
                    </span>
                  </>
                )}
              </p>
              {task.last_output && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground">{t("tasks.output")}</summary>
                  <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 font-mono">{task.last_output}</pre>
                </details>
              )}
            </div>
          ),
        )}
        {act.error && <Alert tone="danger">{errorMessage(act.error)}</Alert>}
        {editing === "new" ? (
          <TaskForm {...formProps} initial={{ ...blank, mode: hasConsole ? "console" : "shell" }} />
        ) : (
          <Button size="sm" variant="outline" className="justify-self-start" onClick={() => setEditing("new")}>
            <Plus /> {t("tasks.add")}
          </Button>
        )}
      </div>
    </CollapsibleCard>
  );
}
