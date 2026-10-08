"use client";

import { useEffect, useState } from "react";

import { CodeEditor, languageOfPath } from "@/components/code-editor";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useSaveSiteFile, useSiteFile } from "./hooks";

type Loaded = { base: string | null; original: string; draft: string };

/** One text file in a code editor. Saved by a job, if the file is still the one read. */
export function FileEditor({ base, path, exists, canEdit, onJob, onDirty }: {
  base: string; // siteApi(…)
  path: string;
  exists: boolean; // false: a new file, created when saved
  canEdit: boolean;
  onJob: (jobId: number) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const { t, errorMessage } = useI18n();
  const file = useSiteFile(base, path, exists);
  const save = useSaveSiteFile(base);
  const [state, setState] = useState<Loaded>({ base: null, original: "", draft: "" });
  const dirty = state.draft !== state.original;
  const conflict = save.error instanceof ApiError && save.error.code === "file_changed";

  // Take the file as read, unless that would drop unsaved changes. Once a save has run,
  // the file read back is the draft itself: it becomes the new base.
  useEffect(() => {
    const data = file.data;
    if (!data) return;
    setState((s) =>
      s.draft === s.original || s.draft === data.content ? { base: data.sha256, original: data.content, draft: data.content } : s,
    );
  }, [file.data]);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const reload = async () => {
    const { data } = await file.refetch();
    if (data) setState({ base: data.sha256, original: data.content, draft: data.content });
    save.reset();
  };
  const canSave = canEdit && !(exists && !dirty) && !save.isPending;
  const submit = () =>
    save.mutate(
      { path, content: state.draft, base_sha256: exists ? state.base : null },
      { onSuccess: (job) => onJob(job.id) },
    );

  if (file.error) return <Alert tone="danger">{errorMessage(file.error)}</Alert>;
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-sm">{path}</span>
        <span className="text-xs text-muted-foreground">
          {!canEdit ? t("sites.readOnly") : !exists ? t("sites.newFileHint") : dirty ? t("sites.unsaved") : ""}
        </span>
      </div>
      {exists && !file.data ? (
        <Skeleton className="h-[28rem]" />
      ) : (
        <CodeEditor
          language={languageOfPath(path)}
          label={t("sites.editorLabel", { path })}
          value={state.draft}
          readOnly={!canEdit}
          onChange={(draft) => setState((s) => ({ ...s, draft }))}
          onSave={() => canSave && submit()}
        />
      )}
      {conflict && (
        <Alert tone="danger">
          {t("sites.conflict")}{" "}
          <Button variant="outline" size="sm" className="ml-2" onClick={() => void reload()}>
            {t("sites.reload")}
          </Button>
        </Alert>
      )}
      {save.error && !conflict && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      {canEdit && (
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={!dirty || save.isPending} onClick={() => setState({ ...state, draft: state.original })}>
            {t("sites.revert")}
          </Button>
          <Button disabled={!canSave} onClick={submit}>
            {t("common.save")}
          </Button>
        </div>
      )}
    </div>
  );
}
