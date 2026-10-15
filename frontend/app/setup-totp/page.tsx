"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TotpCard } from "@/features/account/totp-card";
import { ApiError } from "@/lib/api/client";
import { useLogout, useMe } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** A public panel and no TOTP yet: set it up here (outside the panel, no WebSocket), then
 *  go on once the recovery codes are written down; the session stays signed in. */
export default function SetupTotpPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { data: me, error } = useMe();
  const logout = useLogout();
  const [arrivedWithTotp, setArrivedWithTotp] = useState<boolean | null>(null);
  useEffect(() => {
    if (me && arrivedWithTotp === null) setArrivedWithTotp(me.totp_enabled);
  }, [me, arrivedWithTotp]);
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login/");
    else if (me?.must_change_password) router.replace("/change-password/");
    else if (arrivedWithTotp) router.replace("/"); // nothing to do here
  }, [error, me, arrivedWithTotp, router]);

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("setupTotp.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("setupTotp.why")}</p>
        </CardHeader>
        <CardContent className="grid gap-4">
          {arrivedWithTotp === false && <TotpCard onContinue={() => router.replace("/")} />}
          <Button
            variant="ghost"
            className="justify-self-start"
            onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login/") })}
          >
            {t("nav.logout")}
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
