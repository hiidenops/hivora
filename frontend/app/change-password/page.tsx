"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PasswordForm } from "@/features/account/password-form";
import { ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

export default function ChangePasswordPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { data: me, error } = useMe();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login/");
  }, [error, router]);

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("password.title")}</CardTitle>
          {me?.must_change_password && <p className="text-sm text-muted-foreground">{t("password.forced")}</p>}
        </CardHeader>
        <CardContent>
          {!done && (
            <PasswordForm
              onDone={() => {
                setDone(true);
                router.replace("/");
              }}
            />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
