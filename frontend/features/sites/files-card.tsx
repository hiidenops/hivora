"use client";

import { FileCode } from "lucide-react";
import { useCallback, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n";

import { FileEditor } from "./file-editor";
import { FileTree } from "./file-tree";
import { useSiteFiles } from "./hooks";

/** The site's .html, .css and .js files: pick one to read or edit, or start a new one. `base`: siteApi(…). */
export function FilesCard({ base, canEdit, onJob }: { base: string; canEdit: boolean; onJob: (jobId: number) => void }) {
  const { t, errorMessage } = useI18n();
  const { data, error } = useSiteFiles(base);
  const [path, setPath] = useState<string | null>(null);
  const [newPath, setNewPath] = useState("");
  const [dirty, setDirty] = useState(false);
  const onDirty = useCallback((d: boolean) => setDirty(d), []);
  const files = data?.files ?? [];

  const open = (next: string) => {
    if (next === path || (dirty && !window.confirm(t("sites.discardConfirm")))) return;
    setDirty(false);
    setPath(next);
  };
  const create = (e: FormEvent) => {
    e.preventDefault();
    if (newPath.trim()) open(newPath.trim());
    setNewPath("");
  };

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileCode className="size-5" /> {t("sites.files")}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-[minmax(14rem,18rem)_1fr]">
        <div className="grid content-start gap-3">
          <p className="text-sm text-muted-foreground">{t("sites.filesHelp")}</p>
          {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          {data && files.length === 0 && <p className="text-sm text-muted-foreground">{t("sites.noFiles")}</p>}
          <FileTree files={files} current={path} onOpen={open} label={t("sites.files")} />
          {data?.truncated && <p className="text-xs text-muted-foreground">{t("sites.truncated", { n: files.length })}</p>}
          {canEdit && (
            <form className="flex gap-2" onSubmit={create}>
              <Input
                aria-label={t("sites.newFile")}
                placeholder={t("sites.newFilePlaceholder")}
                value={newPath}
                maxLength={1024}
                className="font-mono"
                onChange={(e) => setNewPath(e.target.value)}
              />
              <Button type="submit" variant="outline" disabled={!newPath.trim()}>
                {t("sites.createFile")}
              </Button>
            </form>
          )}
        </div>
        {path ? (
          <FileEditor
            key={path}
            base={base}
            path={path}
            exists={files.some((f) => f.path === path)}
            canEdit={canEdit}
            onJob={onJob}
            onDirty={onDirty}
          />
        ) : (
          <div className="grid h-[28rem] place-items-center rounded-lg border-2 border-dashed border-input p-6 text-center">
            <span className="grid justify-items-center gap-2 text-sm text-muted-foreground">
              <FileCode aria-hidden className="size-8" />
              {t("sites.pickFile")}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
