"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { CodeView } from "@/components/code-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select, Switch } from "@/components/ui/input";
import { api, type Releases } from "@/lib/api/client";
import { useReleases } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";

import { updateState } from "./releases";

const TONE = { newer: "bg-info/15 text-info", upToDate: "bg-ok/15 text-ok" } as const;

/** Settings → Updates (admins): the installed and the available version, its notes, the
 * command to update (the update itself is the installer: a button comes with M13). */
export function ReleasesCard() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const { data } = useReleases(true);
  const refresh = useMutation({
    mutationFn: () => api<Releases>("/system/releases?refresh=true"),
    onSuccess: (fresh) => qc.setQueryData(["system-releases"], fresh),
  });
  const save = useMutation({
    mutationFn: (body: { enabled: boolean; channel: "stable" | "pre" }) =>
      api<void>("/system/releases/settings", { method: "PUT", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system-releases"] }),
  });
  if (!data) return null;
  const state = updateState(data);
  const latest = data.latest;
  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>{t("releases.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <span>
            {t("releases.installed")} <strong className="font-mono">{data.current}</strong>
          </span>
          <span>
            {t("releases.channel")} <strong>{t(`releases.channel.${data.channel}` as MessageKey)}</strong>
          </span>
          {state in TONE && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONE[state as keyof typeof TONE]}`}>
              {state === "newer" ? t("releases.newer", { version: latest?.version ?? "" }) : t("releases.upToDate")}
            </span>
          )}
        </div>
        {state !== "newer" && state !== "upToDate" && <p className="text-muted-foreground">{t(`releases.state.${state}` as MessageKey)}</p>}
        {latest && state === "newer" && (
          <div className="grid gap-2">
            <p>
              {t("releases.latest", { version: latest.version, date: latest.date ? new Date(latest.date).toLocaleDateString(lang) : "—" })}
              {latest.url && (
                <a href={latest.url} target="_blank" rel="noopener noreferrer" className="ml-2 inline-flex items-center gap-1 underline underline-offset-2">
                  {t("releases.page")} <ExternalLink className="size-3.5" />
                </a>
              )}
            </p>
            {latest.notes && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">{t("releases.notes", { version: latest.version })}</summary>
                <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 text-xs">{latest.notes}</pre>
              </details>
            )}
            {data.command && (
              <div className="grid gap-1">
                <span className="text-muted-foreground">{t("releases.command")}</span>
                <CodeView code={data.command} />
              </div>
            )}
          </div>
        )}
        {data.current_notes && (
          <details>
            <summary className="cursor-pointer text-muted-foreground">{t("releases.currentNotes", { version: data.current })}</summary>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 text-xs">{data.current_notes}</pre>
          </details>
        )}
        <div className="flex flex-wrap items-center gap-4 border-t pt-4">
          <label className="flex items-center gap-2">
            <Switch checked={data.enabled} disabled={save.isPending} onChange={(e) => save.mutate({ enabled: e.target.checked, channel: data.channel })} />
            {t("releases.auto")}
          </label>
          <span className="flex items-center gap-2">
            <Label htmlFor="release-channel" className="whitespace-nowrap">{t("releases.channel")}</Label>
            <Select id="release-channel" value={data.channel} disabled={save.isPending} onChange={(e) => save.mutate({ enabled: data.enabled, channel: e.target.value as "stable" | "pre" })}>
              <option value="stable">{t("releases.channel.stable")}</option>
              <option value="pre">{t("releases.channel.pre")}</option>
            </Select>
          </span>
          {data.enabled && data.available && (
            <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
              {refresh.isPending ? t("status.checking") : t("releases.checkNow")}
            </Button>
          )}
        </div>
        {data.enabled && data.available && (
          <p className="text-xs text-muted-foreground">
            {data.error ? t(`releases.error.${data.error}` as MessageKey) : data.checked_at ? t("releases.checkedAt", { date: new Date(data.checked_at).toLocaleString(lang) }) : ""}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
