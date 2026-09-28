"use client";

import { FileArchive } from "lucide-react";
import { useState } from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { upload, type JobRef } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

/** New code for a Python app: the .zip replaces the code folders (data kept), then a restart. */
export function PythonCodeCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, errorMessage } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const send = async () => {
    if (!file) return;
    setError(null);
    try {
      const job = await upload<JobRef>(`/apps/${appId}/python/code`, file, { onProgress: setProgress });
      onJob(job.id);
      setFile(null);
    } catch (e) {
      setError(e);
    } finally {
      setProgress(null);
    }
  };
  return (
    <CollapsibleCard
      storageKey="app.pycode"
      className="lg:col-span-2"
      title={
        <>
          <FileArchive className="size-5" /> {t("py.code")}
        </>
      }
    >
      <div className="grid gap-3">
        <p className="text-sm text-muted-foreground">{t("py.codeHelp")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Input type="file" accept=".zip,application/zip" aria-label={t("py.zip")} className="max-w-md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button disabled={!file || progress !== null} onClick={() => void send()}>
            {progress !== null ? t("worlds.uploading", { percent: Math.round(progress * 100) }) : t("py.sendCode")}
          </Button>
        </div>
        {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      </div>
    </CollapsibleCard>
  );
}
