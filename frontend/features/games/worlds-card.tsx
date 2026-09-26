"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Globe, Play, Trash2, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { useSession } from "@/components/app-shell";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { units } from "@/features/activity/host-charts";
import { ApiError, api, upload, type JobRef, type Worlds } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

const MAX_UPLOAD = 10 * 1024 ** 3; // same cap as the backend
const WORLD_NAME = "[A-Za-z0-9][A-Za-z0-9_\\-]{0,47}";

/** "My World (1).zip" -> "My_World_1" */
function nameFromFile(file: string): string {
  const base = file
    .replace(/\.zip$/i, "")
    .replace(/[^A-Za-z0-9_-]+/g, "_")
    .replace(/^[_-]+|_+$/g, "");
  return base.slice(0, 48) || "world";
}

function ImportForm({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, errorMessage } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const send = useMutation({
    mutationFn: () => {
      if (file!.size > MAX_UPLOAD) throw new ApiError(413, "archive_too_large", "");
      setProgress(0);
      return upload<JobRef>(`/apps/${appId}/game/worlds`, file!, {
        query: { name, filename: file!.name },
        onProgress: setProgress,
      });
    },
    onSettled: () => setProgress(null),
    onSuccess: (job) => {
      onJob(job.id);
      setFile(null);
      if (input.current) input.current.value = "";
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send.mutate();
  };

  return (
    <form onSubmit={submit} className="grid gap-2 rounded-lg border border-dashed p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          id={`world-file-${appId}`}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            if (f) setName(nameFromFile(f.name));
            send.reset();
          }}
        />
        <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()} disabled={send.isPending}>
          <Upload /> {t("worlds.choose")}
        </Button>
        <span className="min-w-0 truncate text-sm text-muted-foreground">{file ? file.name : t("worlds.importHelp")}</span>
      </div>
      {file && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label htmlFor={`world-name-${appId}`}>{t("worlds.name")}</Label>
            <Input
              id={`world-name-${appId}`}
              className="w-56 font-mono"
              value={name}
              pattern={WORLD_NAME}
              title={t("worlds.nameRule")}
              maxLength={48}
              required
              onChange={(e) => setName(e.target.value)}
              disabled={send.isPending}
            />
          </div>
          <Button type="submit" size="sm" disabled={send.isPending}>
            {t("worlds.import")}
          </Button>
        </div>
      )}
      {progress !== null && (
        <div className="grid gap-1" role="status">
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <span className="text-xs text-muted-foreground">{t("worlds.uploading", { percent: Math.round(progress * 100) })}</span>
        </div>
      )}
      {send.error && <Alert tone="danger">{errorMessage(send.error)}</Alert>}
    </form>
  );
}

/** The server's worlds: switch, download, delete, import a .zip. */
export function WorldsCard({
  appId,
  onJob,
  canImport,
  canActivate,
}: {
  appId: number;
  onJob: (id: number) => void;
  canImport: boolean;
  canActivate: boolean;
}) {
  const { t, lang, errorMessage } = useI18n();
  const { can } = useSession();
  const qc = useQueryClient();
  const key = ["apps", appId, "game", "worlds"];
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Worlds>(`/apps/${appId}/game/worlds`) });
  const u = units(lang);
  const act = useMutation({
    mutationFn: ({ name, remove }: { name: string; remove: boolean }) =>
      remove
        ? api<JobRef>(`/apps/${appId}/game/worlds/${encodeURIComponent(name)}`, { method: "DELETE" })
        : api<JobRef>(`/apps/${appId}/game/worlds/active`, { method: "PUT", body: { name } }),
    onSuccess: (job) => {
      onJob(job.id);
      void qc.invalidateQueries({ queryKey: key });
    },
  });
  const operator = can("operator");

  return (
    <CollapsibleCard
      storageKey="mc.worlds"
      title={
        <>
          <Globe className="size-5" /> {t("worlds.title")}
        </>
      }
      aside={data?.active && <span className="font-mono text-xs text-muted-foreground">{data.active}</span>}
    >
      <div className="grid gap-4">
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
        {!data && !error && <Skeleton className="h-24" />}
        {data && data.worlds.length === 0 && <p className="text-sm text-muted-foreground">{t("worlds.none")}</p>}
        {data && data.worlds.length > 0 && (
          <ul className="divide-y rounded-lg border">
            {data.worlds.map((w) => (
              <li key={w.name} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
                <div className="grid min-w-0 flex-1">
                  <span className="flex items-center gap-2 font-mono text-sm">
                    {w.name}
                    {w.active && <Badge className="bg-ok/15 text-ok">{t("worlds.active")}</Badge>}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {u.size(w.size)} · {new Date(w.modified * 1000).toLocaleString(lang)}
                  </span>
                </div>
                {operator && (
                  <div className="flex gap-1">
                    {!w.active && canActivate && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={act.isPending}
                        onClick={() => window.confirm(t("worlds.activateConfirm", { name: w.name })) && act.mutate({ name: w.name, remove: false })}
                      >
                        <Play /> {t("worlds.activate")}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" asChild>
                      <a
                        href={`/api/v1/apps/${appId}/game/worlds/${encodeURIComponent(w.name)}/download`}
                        download={`${w.name}.zip`}
                        aria-label={t("worlds.download", { name: w.name })}
                        title={t("worlds.download", { name: w.name })}
                      >
                        <Download />
                      </a>
                    </Button>
                    {!w.active && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={act.isPending}
                        aria-label={t("worlds.delete", { name: w.name })}
                        title={t("worlds.delete", { name: w.name })}
                        onClick={() => window.confirm(t("worlds.deleteConfirm", { name: w.name })) && act.mutate({ name: w.name, remove: true })}
                      >
                        <Trash2 className="text-danger" />
                      </Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {act.error && <Alert tone="danger">{errorMessage(act.error)}</Alert>}
        {operator && canImport && <ImportForm appId={appId} onJob={onJob} />}
      </div>
    </CollapsibleCard>
  );
}
