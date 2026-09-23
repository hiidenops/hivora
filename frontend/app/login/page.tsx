"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { useLogin } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

export default function LoginPage() {
  const { t, errorMessage } = useI18n();
  const router = useRouter();
  const login = useLogin();
  const [needTotp, setNeedTotp] = useState(false);

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    login.mutate(
      {
        username: String(f.get("username")),
        password: String(f.get("password")),
        totp_code: needTotp ? String(f.get("totp") ?? "") : undefined,
      },
      {
        onSuccess: (me) => router.replace(me.must_change_password ? "/change-password/" : "/"),
        onError: (err) => {
          if (err instanceof ApiError && err.code === "totp_required") setNeedTotp(true);
        },
      },
    );
  };

  const error = login.error instanceof ApiError && login.error.code === "totp_required" ? null : login.error;

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="mb-2 grid size-10 place-items-center rounded-lg bg-primary font-mono text-lg text-primary-foreground">
            H
          </div>
          <CardTitle className="text-xl">{t("login.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={submit}>
            <div className="grid gap-1.5">
              <Label htmlFor="username">{t("login.username")}</Label>
              <Input id="username" name="username" autoComplete="username" required autoFocus />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="password">{t("login.password")}</Label>
              <Input id="password" name="password" type="password" autoComplete="current-password" required />
            </div>
            {needTotp && (
              <div className="grid gap-1.5">
                <Label htmlFor="totp">{t("login.totp")}</Label>
                <Input id="totp" name="totp" autoComplete="one-time-code" className="font-mono" required autoFocus />
              </div>
            )}
            {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
            <Button type="submit" disabled={login.isPending}>
              {t("login.submit")}
            </Button>
            <p className="text-xs text-muted-foreground">{t("login.defaultHint")}</p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
