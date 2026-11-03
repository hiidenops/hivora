"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

/** The code asked for before an action that needs a recent TOTP. */
export function TotpForm({ onCode, pending }: { onCode: (code: string) => void; pending: boolean }) {
  const { t } = useI18n();
  const [code, setCode] = useState("");
  return (
    <form
      className="surface flex flex-wrap items-end gap-2 rounded-md border p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onCode(code);
        setCode("");
      }}
    >
      <p className="w-full">{t("releases.totp")}</p>
      <Input aria-label={t("releases.totp")} className="w-40 font-mono" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
      <Button type="submit" size="sm" loading={pending}>
        {t("settings.totp.verify")}
      </Button>
    </form>
  );
}

/** ``run(arg)`` calls ``fn``; a ``totp_required`` refusal shows the code form (``totp``),
 *  then the same call again once the code is confirmed. */
export function useConfirmed<A, R>(fn: (arg: A) => Promise<R>, onDone?: (result: R) => void) {
  const [pending, setPending] = useState<{ arg: A } | null>(null);
  const m = useMutation({
    mutationFn: async ({ arg, code }: { arg: A; code?: string }) => {
      if (code) await api("/system/confirm", { method: "POST", body: { code } });
      try {
        return { done: true as const, result: await fn(arg) };
      } catch (e) {
        if (e instanceof ApiError && e.code === "totp_required") {
          setPending({ arg });
          return { done: false as const };
        }
        throw e;
      }
    },
    onSuccess: (r) => {
      if (!r.done) return;
      setPending(null);
      onDone?.(r.result);
    },
  });
  return {
    run: (arg: A) => m.mutate({ arg }),
    totp: pending && <TotpForm pending={m.isPending} onCode={(code) => m.mutate({ arg: pending.arg, code })} />,
    isPending: m.isPending,
    error: m.error,
    reset: () => {
      setPending(null);
      m.reset();
    },
  };
}
