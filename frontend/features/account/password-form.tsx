"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { useChangePassword } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const { t, errorMessage } = useI18n();
  const change = useChangePassword();
  const [mismatch, setMismatch] = useState(false);

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const next = String(f.get("new"));
    if (next !== String(f.get("confirm"))) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    change.mutate(
      { current: String(f.get("current")), new: next },
      {
        onSuccess: () => {
          form.reset();
          onDone?.();
        },
      },
    );
  };

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <div className="grid gap-1.5">
        <Label htmlFor="current">{t("password.current")}</Label>
        <Input id="current" name="current" type="password" autoComplete="current-password" required />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="new">{t("password.new")}</Label>
        <Input id="new" name="new" type="password" autoComplete="new-password" minLength={10} required />
        <p className="text-xs text-muted-foreground">{t("password.rules")}</p>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="confirm">{t("password.confirm")}</Label>
        <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
      </div>
      {mismatch && <Alert tone="danger">{t("password.mismatch")}</Alert>}
      {change.error && <Alert tone="danger">{errorMessage(change.error)}</Alert>}
      {change.isSuccess && <Alert>{t("password.changed")}</Alert>}
      <Button type="submit" disabled={change.isPending}>
        {t("common.save")}
      </Button>
    </form>
  );
}
