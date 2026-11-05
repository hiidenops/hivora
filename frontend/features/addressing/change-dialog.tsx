"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { CodeView } from "@/components/code-view";
import { DiffView } from "@/components/diff-view";
import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { api, type AddressChange } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

/** One addressing change (a zone's subnet, a service's address, the Hivora range): typed,
 *  previewed (the value given, the apps redeployed, the Docker commands or compose diff),
 *  then applied, each redeploy followed in a pop-up. ``automatic``: an empty value gives
 *  the choice back to Hivora. */
export function ChangeDialog({ trigger, title, help, label, initial, placeholder, path, body, automatic = false }: {
  trigger: ReactNode;
  title: string;
  help: string;
  label: string;
  initial: string;
  placeholder: string;
  path: string;
  body: (value: string | null) => Record<string, unknown>;
  automatic?: boolean;
}) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const track = useTrackJob();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(initial);
  const [preview, setPreview] = useState<AddressChange | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const chosen = value.trim() || null;

  const send = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const out = await api<AddressChange>(path, { method: "PUT", body: { ...body(chosen), dry_run: dryRun } });
      if (dryRun) {
        setPreview(out);
        return;
      }
      const refresh = () => void qc.invalidateQueries({ queryKey: ["addressing"] });
      out.jobs?.forEach((j) => track(j.id, refresh));
      refresh();
      void qc.invalidateQueries({ queryKey: ["zones"] });
      setOpen(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(preview === null);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setValue(initial);
          setPreview(null);
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent title={title} description={help} closeLabel={t("common.close")} className="max-w-xl">
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="addressing-value">{label}</Label>
            <Input
              id="addressing-value"
              className="font-mono"
              value={value}
              placeholder={placeholder}
              autoComplete="off"
              spellCheck={false}
              required={!automatic}
              onChange={(e) => {
                setValue(e.target.value);
                setPreview(null); // a new value: previewed again before it is applied
              }}
            />
            {automatic && <p className="text-xs text-muted-foreground">{t("addr.emptyAutomatic")}</p>}
          </div>
          {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          {preview && (
            <div className="grid gap-3 rounded-lg border bg-muted/30 p-3 text-sm">
              <p>
                {t("addr.preview.value")} <span className="font-mono font-medium">{preview.value ?? t("addr.automatic")}</span>
              </p>
              <p>
                {preview.apps.length === 0
                  ? t("addr.preview.noApp")
                  : t("addr.preview.apps", { apps: preview.apps.join(", ") })}
              </p>
              {preview.vpn && <Alert tone="warn">{t("addr.preview.vpn", { vpn: preview.vpn })}</Alert>}
              {preview.commands.length > 0 && <CodeView code={preview.commands.join("\n")} />}
              {preview.diff && <DiffView diff={preview.diff} />}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button type="submit" loading={busy} disabled={busy} variant={preview ? "default" : "outline"}>
              {preview ? t("addr.apply") : t("addr.preview")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
