"use client";

import { FileArchive } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { FileDrop } from "@/components/file-drop";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, upload, type JobRef } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

const MAX_UPLOAD = 200 * 1024 ** 2; // the backend's limit: refused before sending

/** Replace the whole site with a .zip: sent, checked, then extracted by a job. `base`: siteApi(…). */
export function ContentCard({ base, onJob }: { base: string; onJob: (jobId: number) => void }) {
  const { t, errorMessage } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const send = async () => {
    if (!file || !window.confirm(t("sites.replaceConfirm"))) return;
    setError(null);
    try {
      if (file.size > MAX_UPLOAD) throw new ApiError(413, "archive_too_large", "");
      const job = await upload<JobRef>(`${base}/content`, file, {
        method: "PUT",
        query: { filename: file.name },
        onProgress: setProgress,
      });
      onJob(job.id);
      setFile(null);
    } catch (e) {
      setError(e);
    } finally {
      setProgress(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileArchive className="size-5" /> {t("sites.content")}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">{t("sites.contentHelp")}</p>
        <Alert tone="warn">{t("sites.replaceWarning")}</Alert>
        <FileDrop
          label={t("sites.zip")}
          accept=".zip,application/zip"
          file={file}
          disabled={progress !== null}
          onFile={(f) => {
            setFile(f);
            setError(null);
          }}
        />
        <Button className="justify-self-center" disabled={!file || progress !== null} onClick={() => void send()}>
          {progress !== null ? t("worlds.uploading", { percent: Math.round(progress * 100) }) : t("sites.replace")}
        </Button>
        {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      </CardContent>
    </Card>
  );
}
