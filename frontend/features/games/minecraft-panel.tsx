"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, UserPlus, Users, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type GameAccess, type JobRef, type Players } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

const NAME = "[A-Za-z0-9_]{3,16}";

function PlayersCard({ appId, running }: { appId: number; running: boolean }) {
  const { t, errorMessage } = useI18n();
  const { data, error, isPending } = useQuery({
    queryKey: ["apps", appId, "minecraft", "players", running],
    queryFn: () => api<Players>(`/apps/${appId}/minecraft/players`),
    refetchInterval: running ? 15_000 : false,
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Users className="size-5" /> {t("mc.players")}
        </CardTitle>
        {data?.running && data.online !== null && (
          <span className="text-sm font-medium tabular-nums">
            {t("mc.online", { online: data.online, max: data.max ?? "?" })}
          </span>
        )}
      </CardHeader>
      <CardContent>
        {isPending && <Skeleton className="h-8" />}
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
        {data && !data.running && <p className="text-sm text-muted-foreground">{t("mc.offline")}</p>}
        {data?.running && data.names.length === 0 && <p className="text-sm text-muted-foreground">{t("mc.nobody")}</p>}
        <ul className="flex flex-wrap gap-2">
          {data?.names.map((n) => (
            <li key={n}>
              <Badge className="gap-1.5 py-1 text-sm">
                <span className="size-2 rounded-full bg-ok" aria-hidden /> {n}
              </Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function NameList({
  title,
  icon: Icon,
  names,
  disabled,
  onAdd,
  onRemove,
  busy,
}: {
  title: string;
  icon: typeof Users;
  names: { name: string; extra?: string }[];
  disabled: boolean;
  busy: boolean;
  onAdd: (name: string) => void;
  onRemove: (name: string) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onAdd(name);
    setName("");
  };
  const id = `add-${title.replace(/\W+/g, "-")}`;
  return (
    <div className="grid gap-2">
      <h4 className="flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4" /> {title}
      </h4>
      {names.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("mc.empty")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {names.map((n) => (
            <li key={n.name}>
              <Badge className="gap-1 py-1 pr-1 text-sm">
                {n.name}
                {n.extra && <span className="text-xs text-muted-foreground">{n.extra}</span>}
                <button
                  className="rounded p-0.5 hover:bg-muted disabled:opacity-40"
                  disabled={disabled || busy}
                  aria-label={t("mc.remove", { name: n.name })}
                  onClick={() => onRemove(n.name)}
                >
                  <X className="size-3.5" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex gap-2">
        <Label htmlFor={id} className="sr-only">
          {t("mc.playerName")}
        </Label>
        <Input
          id={id}
          className="w-48 font-mono"
          placeholder={t("mc.playerName")}
          pattern={NAME}
          title={t("mc.nameRule")}
          value={name}
          maxLength={16}
          onChange={(e) => setName(e.target.value)}
          disabled={disabled}
          required
        />
        <Button type="submit" size="sm" variant="outline" disabled={disabled || busy}>
          <UserPlus /> {t("mc.add")}
        </Button>
      </form>
    </div>
  );
}

function AccessCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const qc = useQueryClient();
  const key = ["apps", appId, "minecraft", "access"];
  const { data } = useQuery({ queryKey: key, queryFn: () => api<GameAccess>(`/apps/${appId}/minecraft/access`) });
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  // Shows the requested whitelist state right away; the server applies it on restart.
  const [wanted, setWanted] = useState<boolean | null>(null);
  const command = useMutation({
    mutationFn: ({ list, name, add }: { list: "whitelist" | "ops"; name: string; add: boolean }) =>
      add
        ? api(`/apps/${appId}/minecraft/${list}`, { method: "POST", body: { name } })
        : api(`/apps/${appId}/minecraft/${list}/${encodeURIComponent(name)}`, { method: "DELETE" }),
    // The server writes its JSON files right after the command.
    onSuccess: () => setTimeout(() => void refresh(), 500),
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api<JobRef>(`/apps/${appId}/minecraft/whitelist-enabled`, { method: "PUT", body: { enabled } }),
    onMutate: (enabled) => setWanted(enabled),
    onError: () => setWanted(null),
    onSuccess: (job) => {
      onJob(job.id);
      void refresh();
    },
  });
  const operator = can("operator");
  const locked = !data?.running || !operator;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("mc.access")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        {!data ? (
          <Skeleton className="h-32" />
        ) : (
          <>
            <label className="flex items-start gap-3 text-sm">
              <Switch
                checked={wanted ?? data.whitelist_enabled}
                disabled={!operator || toggle.isPending}
                onChange={(e) => window.confirm(t("mc.whitelistConfirm")) && toggle.mutate(e.target.checked)}
              />
              <span>
                <span className="block font-medium">{t("mc.whitelist")}</span>
                <span className="text-muted-foreground">
                  {(wanted ?? data.whitelist_enabled) ? t("mc.whitelistOn") : t("mc.whitelistOff")}
                </span>
              </span>
            </label>
            {!data.running && operator && <p className="text-xs text-muted-foreground">{t("mc.needsRunning")}</p>}
            <NameList
              title={t("mc.whitelist")}
              icon={Users}
              names={data.whitelist.map((name) => ({ name }))}
              disabled={locked}
              busy={command.isPending}
              onAdd={(name) => command.mutate({ list: "whitelist", name, add: true })}
              onRemove={(name) => command.mutate({ list: "whitelist", name, add: false })}
            />
            <NameList
              title={t("mc.ops")}
              icon={Crown}
              names={data.ops.map((o) => ({ name: o.name, extra: t("mc.level", { level: o.level }) }))}
              disabled={locked}
              busy={command.isPending}
              onAdd={(name) => command.mutate({ list: "ops", name, add: true })}
              onRemove={(name) => command.mutate({ list: "ops", name, add: false })}
            />
          </>
        )}
        {(command.error ?? toggle.error) && <Alert tone="danger">{errorMessage(command.error ?? toggle.error)}</Alert>}
      </CardContent>
    </Card>
  );
}

export function MinecraftPanel({
  appId,
  running,
  onJob,
}: {
  appId: number;
  running: boolean;
  onJob: (jobId: number) => void;
}) {
  return (
    <>
      <PlayersCard appId={appId} running={running} />
      <AccessCard appId={appId} onJob={onJob} />
    </>
  );
}
