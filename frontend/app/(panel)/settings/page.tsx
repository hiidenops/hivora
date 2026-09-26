"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { applyTheme } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch, Label, Select } from "@/components/ui/input";
import { IntegrationsCard, PublicAddressCard } from "@/features/account/integrations-card";
import { PasswordForm } from "@/features/account/password-form";
import { TotpCard } from "@/features/account/totp-card";
import { api } from "@/lib/api/client";
import { useLogout, useMySessions, useSystemInfo } from "@/lib/api/hooks";
import { LANGS, useI18n, type Lang, type MessageKey } from "@/lib/i18n";
import { readPref, writePref } from "@/lib/prefs";

function Sessions() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const { data: sessions } = useMySessions();
  const revoke = useMutation({
    mutationFn: (id: number) => api<void>(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  return (
    <ul className="divide-y text-sm">
      {sessions?.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <span>
            <span className="font-mono text-xs">{s.ip ?? "?"}</span>
            <span className="ml-2 text-xs text-muted-foreground">{new Date(s.last_seen_at).toLocaleString(lang)}</span>
            <span className="block max-w-md truncate text-xs text-muted-foreground">{s.user_agent}</span>
          </span>
          {s.current ? (
            <span className="text-xs font-medium">{t("settings.sessions.current")}</span>
          ) : (
            <Button variant="outline" size="sm" onClick={() => revoke.mutate(s.id)}>
              {t("settings.sessions.revoke")}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function SettingsPage() {
  const { t, lang, setLang } = useI18n();
  const { advanced, setAdvanced, can } = useSession();
  const router = useRouter();
  const logout = useLogout();
  const { data: system } = useSystemInfo();
  const [theme, setTheme] = useState("system");
  useEffect(() => setTheme(readPref("theme") ?? "system"), []);

  return (
    <>
      <PageHeader
        title={t("settings.title")}
        actions={
          <Button variant="outline" onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login/") })}>
            {t("nav.logout")}
          </Button>
        }
      />
      <div className="grid max-w-3xl gap-4">
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.account")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="lang">{t("settings.language")}</Label>
              <Select id="lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
                {LANGS.map((l) => (
                  <option key={l} value={l}>
                    {l === "fr" ? "Français" : "English"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="theme">{t("settings.theme")}</Label>
              <Select
                id="theme"
                value={theme}
                onChange={(e) => {
                  setTheme(e.target.value);
                  writePref("theme", e.target.value);
                  applyTheme(e.target.value);
                }}
              >
                <option value="system">{t("settings.theme.system")}</option>
                <option value="light">{t("settings.theme.light")}</option>
                <option value="dark">{t("settings.theme.dark")}</option>
              </Select>
            </div>
            <label className="flex items-center gap-2 self-end pb-2 text-sm">
              <Switch checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
              {t("nav.advanced")}
            </label>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("password.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <PasswordForm />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.totp")}</CardTitle>
          </CardHeader>
          <CardContent>
            <TotpCard />
          </CardContent>
        </Card>
        {can("admin") && (
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.integrations")}</CardTitle>
            </CardHeader>
            <CardContent>
              <IntegrationsCard />
              <hr className="my-5" />
              <PublicAddressCard />
            </CardContent>
          </Card>
        )}
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.sessions")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Sessions />
          </CardContent>
        </Card>
        {system && (
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.system")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                {(
                  [
                    ["settings.system.version", system.version],
                    ["settings.system.docker", system.docker_version ?? "—"],
                    ["settings.system.arch", `${t(`arch.${system.arch}` as MessageKey)} (${system.arch})`],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-muted-foreground">{t(k)}</dt>
                    <dd className="font-mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
