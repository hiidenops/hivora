"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, UserPlus, Users, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Input, Label, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type GameCaps, type GameLists, type JobRef, type Players } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

import { WorldsCard } from "./worlds-card";

/** Players online, polled every 15 s while the server runs (shared cache key). */
export function usePlayers(appId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.game(appId), "players"],
    queryFn: () => api<Players>(`/apps/${appId}/game/players`),
    refetchInterval: enabled ? 15_000 : false,
    enabled,
  });
}

function PlayersCard({ appId, running }: { appId: number; running: boolean }) {
  const { t, errorMessage } = useI18n();
  const { data, error, isPending } = usePlayers(appId, running);
  return (
    <CollapsibleCard
      storageKey="mc.players"
      title={
        <>
          <Users className="size-5" /> {t("mc.players")}
        </>
      }
      aside={
        data?.running &&
        data.online !== null && (
          <span className="text-sm font-medium tabular-nums">
            {t("mc.online", { online: data.online, max: data.max ?? "?" })}
          </span>
        )
      }
    >
        {!running && <p className="text-sm text-muted-foreground">{t("mc.offline")}</p>}
        {running && isPending && <Skeleton className="h-8" />}
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}

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
    </CollapsibleCard>
  );
}

function NameList({
  title,
  icon: Icon,
  pattern,
  names,
  disabled,
  onAdd,
  onRemove,
  busy,
}: {
  title: string;
  icon: typeof Users;
  pattern: string;
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
          pattern={pattern}
          value={name}
          maxLength={64}
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

function ListsCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, l, errorMessage } = useI18n();
  const { can } = useSession();
  const qc = useQueryClient();
  const key = [...keys.game(appId), "lists"];
  const { data } = useQuery({ queryKey: key, queryFn: () => api<GameLists>(`/apps/${appId}/game/lists`) });
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  // Shows the requested on/off state right away; the server applies it on restart.
  const [wanted, setWanted] = useState<Record<string, boolean>>({});
  const command = useMutation({
    mutationFn: ({ list, name, add }: { list: string; name: string; add: boolean }) =>
      add
        ? api(`/apps/${appId}/game/lists/${list}`, { method: "POST", body: { name } })
        : api(`/apps/${appId}/game/lists/${list}/${encodeURIComponent(name)}`, { method: "DELETE" }),
    // The server writes its files right after the command.
    onSuccess: () => setTimeout(() => void refresh(), 500),
  });
  const toggle = useMutation({
    mutationFn: ({ list, enabled }: { list: string; enabled: boolean }) =>
      api<JobRef>(`/apps/${appId}/game/lists/${list}/enabled`, { method: "PUT", body: { enabled } }),
    onMutate: ({ list, enabled }) => setWanted((w) => ({ ...w, [list]: enabled })),
    onError: (_, { list }) =>
      setWanted((w) => {
        const { [list]: _dropped, ...rest } = w;
        return rest;
      }),
    onSuccess: (job) => {
      onJob(job.id);
      void refresh();
    },
  });
  const operator = can("operator");
  const on = (list: GameLists["lists"][number]) => wanted[list.id] ?? list.enabled;

  return (
    <CollapsibleCard
      storageKey="mc.access"
      title={
        <>
          <Crown className="size-5" /> {t("mc.access")}
        </>
      }
    >
      <div className="grid gap-5">
        {!data ? (
          <Skeleton className="h-32" />
        ) : (
          data.lists.map((list) => (
            <div key={list.id} className="grid gap-3">
              {list.enabled !== null && (
                <label className="flex items-start gap-3 text-sm">
                  <Switch
                    checked={!!on(list)}
                    disabled={!operator || toggle.isPending}
                    onChange={(e) =>
                      window.confirm(t("game.listConfirm", { list: l(list.label) })) &&
                      toggle.mutate({ list: list.id, enabled: e.target.checked })
                    }
                  />
                  <span>
                    <span className="block font-medium">{l(list.label)}</span>
                    <span className="text-muted-foreground">{on(list) ? t("game.listOn") : t("game.listOff")}</span>
                  </span>
                </label>
              )}
              <NameList
                title={l(list.label)}
                icon={list.enabled === null ? Crown : Users}
                pattern={list.name_pattern.replace(/^\^|\$$/g, "")}
                names={list.entries.map((e) => ({ name: e.name, extra: e.extra ?? undefined }))}
                disabled={!list.editable || !operator}
                busy={command.isPending}
                onAdd={(name) => command.mutate({ list: list.id, name, add: true })}
                onRemove={(name) => command.mutate({ list: list.id, name, add: false })}
              />
            </div>
          ))
        )}
        {data && !data.running && operator && data.lists.some((x) => !x.editable) && (
          <p className="text-xs text-muted-foreground">{t("mc.needsRunning")}</p>
        )}
        {(command.error ?? toggle.error) && <Alert tone="danger">{errorMessage(command.error ?? toggle.error)}</Alert>}
      </div>
    </CollapsibleCard>
  );
}

/** Cards for what the template's `game` section declares; each keeps its own height. */
export function GamePanel({
  appId,
  caps,
  running,
  onJob,
}: {
  appId: number;
  caps: GameCaps;
  running: boolean;
  onJob: (jobId: number) => void;
}) {
  return (
    <div className="stagger grid items-start gap-4 lg:col-span-2 xl:grid-cols-3">
      {caps.players && <PlayersCard appId={appId} running={running} />}
      {caps.lists && <ListsCard appId={appId} onJob={onJob} />}
      {caps.worlds && (
        <WorldsCard appId={appId} onJob={onJob} canImport={caps.world_import} canActivate={caps.world_activate} />
      )}
    </div>
  );
}
