"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Brand } from "@/components/brand";
import { EnteringScreen } from "@/components/entering-screen";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { SourceLink } from "@/features/system/source-link";
import { ApiError, api } from "@/lib/api/client";
import { useLogin } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

export default function LoginPage() {
  const { t, errorMessage } = useI18n();
  const router = useRouter();
  const login = useLogin();
  // The admin/admin hint only while that initial account is still unchanged.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ first_start: boolean }>("/system/health"),
  });
  const [needTotp, setNeedTotp] = useState(false);
  const [entering, setEntering] = useState(false);

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
        onSuccess: (me) => {
          // A short transition, even when nothing has to load: entering feels smooth.
          setEntering(true);
          const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          setTimeout(() => router.replace(me.must_change_password ? "/change-password/" : "/"), reduced ? 150 : 900);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.code === "totp_required") setNeedTotp(true);
        },
      },
    );
  };

  const error = login.error instanceof ApiError && login.error.code === "totp_required" ? null : login.error;

  if (entering) return <EnteringScreen />;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center gap-5 text-center">
          <Brand large />
          <CardTitle className="text-lg">{t("login.title")}</CardTitle>
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
            {health?.first_start && <p className="text-xs text-muted-foreground">{t("login.defaultHint")}</p>}
          </form>
        </CardContent>
      </Card>
      <SourceLink className="mt-4" />
    </main>
  );
}
