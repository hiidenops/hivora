"use client";

import { useState } from "react";

import { CodeView } from "@/components/code-view";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { keys, useMe } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useMutation, useQueryClient } from "@tanstack/react-query";

async function qrSvg(uri: string): Promise<string> {
  const { default: qrcode } = await import("qrcode-generator"); // only loaded here
  const qr = qrcode(0, "M");
  qr.addData(uri);
  qr.make();
  return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
}

/** `onContinue`: the forced setup of a public panel (/setup-totp/): no "Disable", and a
 *  button to leave once the recovery codes are shown. */
export function TotpCard({ onContinue }: { onContinue?: () => void } = {}) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [enrollment, setEnrollment] = useState<{ secret: string; svg: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: keys.me });

  const enroll = useMutation({
    mutationFn: async () => {
      const e = await api<{ secret: string; uri: string }>("/auth/totp/enroll", { method: "POST" });
      return { secret: e.secret, svg: await qrSvg(e.uri) };
    },
    onSuccess: setEnrollment,
  });
  const confirm = useMutation({
    mutationFn: (code: string) =>
      api<{ recovery_codes: string[] }>("/auth/totp/confirm", { method: "POST", body: { code } }),
    onSuccess: (r) => {
      setCodes(r.recovery_codes);
      setEnrollment(null);
      void refresh();
    },
  });
  const disable = useMutation({
    mutationFn: (password: string) => api<void>("/auth/totp/disable", { method: "POST", body: { password } }),
    onSuccess: () => void refresh(),
  });
  const error = enroll.error ?? confirm.error ?? disable.error;

  return (
    <div className="grid gap-4">
      <p className="text-sm">
        {me?.totp_enabled ? t("settings.totp.enabled") : t("settings.totp.disabled")}
      </p>
      {codes && (
        <div className="grid gap-2">
          <Alert tone="warn">{t("settings.totp.recovery")}</Alert>
          <CodeView code={codes.join("\n")} />
          {onContinue && (
            <Button className="justify-self-start" onClick={onContinue}>
              {t("settings.totp.continue")}
            </Button>
          )}
        </div>
      )}
      {!me?.totp_enabled && !enrollment && (
        <Button className="justify-self-start" onClick={() => enroll.mutate()} disabled={enroll.isPending}>
          {t("settings.totp.enable")}
        </Button>
      )}
      {enrollment && (
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate(String(new FormData(e.currentTarget).get("code")));
          }}
        >
          <p className="text-sm text-muted-foreground">{t("settings.totp.scan")}</p>
          <div
            className="size-48 rounded-md bg-white p-2 [&_svg]:size-full"
            role="img"
            aria-label="QR code"
            dangerouslySetInnerHTML={{ __html: enrollment.svg }}
          />
          <code className="break-all font-mono text-xs">{enrollment.secret}</code>
          <Label htmlFor="totp-code">{t("settings.totp.code")}</Label>
          <Input id="totp-code" name="code" inputMode="numeric" autoComplete="one-time-code" className="w-40 font-mono" required />
          <Button type="submit" className="justify-self-start" disabled={confirm.isPending}>
            {t("settings.totp.verify")}
          </Button>
        </form>
      )}
      {me?.totp_enabled && !onContinue && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            disable.mutate(String(new FormData(e.currentTarget).get("password")));
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="totp-password">{t("settings.totp.passwordToDisable")}</Label>
            <Input id="totp-password" name="password" type="password" autoComplete="current-password" required />
          </div>
          <Button type="submit" variant="outline" disabled={disable.isPending}>
            {t("settings.totp.disable")}
          </Button>
        </form>
      )}
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
    </div>
  );
}
