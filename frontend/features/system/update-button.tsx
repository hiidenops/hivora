"use client";

import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, type JobRef } from "@/lib/api/client";
import { useI18n, type MessageKey } from "@/lib/i18n";

/** The Update button (M13): confirmed, then a TOTP code if asked; Hivora restarts, the page
 *  waits for it and reloads on the new version, or says why it stayed on this one. */
export function UpdateButton({ tag, version, current }: { tag: string; version: string; current: string }) {
  const { t, errorMessage } = useI18n();
  const [totp, setTotp] = useState(false);
  const [code, setCode] = useState("");
  const [job, setJob] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: async (withCode?: string) => {
      if (withCode) await api("/system/confirm", { method: "POST", body: { code: withCode } });
      try {
        return await api<JobRef>("/system/update", { method: "POST", body: { tag } });
      } catch (e) {
        if (e instanceof ApiError && e.code === "totp_required") {
          setTotp(true);
          return null;
        }
        throw e;
      }
    },
    onSuccess: (ref) => {
      if (!ref) return;
      setTotp(false);
      setJob(ref.id);
    },
  });

  // While Hivora restarts nothing answers: poll its health, then the job's result.
  useEffect(() => {
    if (job === null) return;
    const timer = window.setInterval(async () => {
      try {
        const health = await api<{ version: string }>("/system/health");
        if (health.version !== current) return window.location.reload();
        const j = await api<{ status: string; error: string | null }>(`/jobs/${job}`);
        if (j.status === "failed" || j.status === "interrupted") {
          setFailed(j.error ?? j.status);
          setJob(null);
        }
      } catch {
        // restarting
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [job, current]);

  const refusal =
    start.error instanceof ApiError && start.error.code === "self_update_refused"
      ? t(`releases.refused.${String(start.error.details.reason)}` as MessageKey)
      : start.error && errorMessage(start.error);

  if (job !== null) return <Alert tone="info" role="status">{t("releases.updating", { version })}</Alert>;
  return (
    <div className="grid gap-2">
      <Button
        className="justify-self-start"
        loading={start.isPending}
        disabled={start.isPending}
        onClick={() => window.confirm(t("releases.updateConfirm", { version })) && start.mutate(undefined)}
      >
        <Download /> {t("releases.update", { version })}
      </Button>
      {totp && (
        <form
          className="surface flex flex-wrap items-end gap-2 rounded-md border p-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate(code);
            setCode("");
          }}
        >
          <p className="w-full">{t("releases.totp")}</p>
          <Input aria-label={t("releases.totp")} className="w-40 font-mono" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
          <Button type="submit" size="sm" disabled={start.isPending}>
            {t("settings.totp.verify")}
          </Button>
        </form>
      )}
      {refusal && <Alert tone="danger">{refusal}</Alert>}
      {failed && <Alert tone="danger">{t("releases.updateFailed", { error: failed })}</Alert>}
    </div>
  );
}
