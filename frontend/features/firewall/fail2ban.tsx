"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { KEY, box, useHost } from "./host";

/** The fail2ban page: the jails and their banned addresses, beside their settings. */
export function Fail2banSection() {
  const { state } = useHost();
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <Jails />
      {state.data?.fail2ban_running && <JailSettings />}
    </div>
  );
}

/** Each jail: its banned addresses (unban), and an address to ban. */
export function Jails() {
  const { t } = useI18n();
  const { state, act } = useHost();
  const [ban, setBan] = useState<Record<string, string>>({});
  const data = state.data;
  if (!data) return null;
  return (
    <section className={box}>
      <h3 className="font-semibold">fail2ban</h3>
      {!data.fail2ban_installed ? (
        <p className="text-muted-foreground">{t("fw.f2bMissing")}</p>
      ) : !data.fail2ban_running ? (
        <p className="text-muted-foreground">{t("fw.f2bStopped")}</p>
      ) : (
        data.jails.map((j) => (
          <div key={j.name} className="grid gap-1 rounded border p-2">
            <p className="font-medium">
              {j.name}{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {t("fw.jailStats", {
                  banned: j.banned.length,
                  total: j.total_banned,
                  failed: j.failed,
                })}
              </span>
            </p>
            <ul className="flex flex-wrap gap-1">
              {j.banned.map((ip) => (
                <li key={ip} className="flex items-center gap-1 rounded bg-danger/10 px-2 py-0.5 font-mono text-xs">
                  {ip}
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={t("fw.unban", { ip })}
                    title={t("fw.unban", { ip })}
                    onClick={() =>
                      act(() =>
                        api(`/host-firewall/fail2ban/${j.name}`, {
                          method: "POST",
                          body: { ip, ban: false },
                        }),
                      )
                    }
                  >
                    <X className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                act(() =>
                  api(`/host-firewall/fail2ban/${j.name}`, {
                    method: "POST",
                    body: { ip: ban[j.name], ban: true },
                  }),
                );
              }}
            >
              <Input
                className="h-8 w-44 font-mono text-xs"
                required
                placeholder="203.0.113.5"
                value={ban[j.name] ?? ""}
                onChange={(e) => setBan({ ...ban, [j.name]: e.target.value })}
                aria-label={t("fw.banIp")}
              />
              <Button size="sm" variant="outline" type="submit">
                {t("fw.ban")}
              </Button>
            </form>
          </div>
        ))
      )}
    </section>
  );
}

type Jail = { maxretry: string; bantime: string; findtime: string };

/** maxretry / bantime / findtime per jail, written to jail.d/hivora.local then reloaded. */
function JailSettings() {
  const { t } = useI18n();
  const { act } = useHost();
  const { data } = useQuery({
    queryKey: [...KEY, "jails"],
    queryFn: () => api<Record<string, Jail>>("/host-firewall/fail2ban/settings"),
  });
  const [edit, setEdit] = useState<Record<string, Jail> | null>(null);
  const jails = edit ?? data ?? {};
  const set = (name: string, key: keyof Jail, value: string) => setEdit({ ...jails, [name]: { ...jails[name], [key]: value } });
  const save = (e: FormEvent) => {
    e.preventDefault();
    const body = Object.fromEntries(
      Object.entries(jails).map(([name, j]) => [
        name,
        {
          maxretry: Number(j.maxretry) || null,
          bantime: j.bantime || null,
          findtime: j.findtime || null,
        },
      ]),
    );
    act(async () => {
      await api("/host-firewall/fail2ban/settings", {
        method: "PUT",
        body: { jails: body },
      });
      setEdit(null);
    });
  };
  return (
    <form className={box} onSubmit={save}>
      <h3 className="font-semibold">{t("fw.jailSettings")}</h3>
      <p className="text-xs text-muted-foreground">{t("fw.jailSettingsHelp")}</p>
      {Object.entries(jails).map(([name, j]) => (
        <div key={name} className="flex flex-wrap items-center gap-2">
          <span className="w-32 font-medium">{name}</span>
          {(["maxretry", "findtime", "bantime"] as const).map((k) => (
            <label key={k} className="flex items-center gap-1 text-xs">
              {t(`fw.${k}`)}
              <Input className="h-8 w-20 font-mono text-xs" value={j[k]} onChange={(e) => set(name, k, e.target.value)} />
            </label>
          ))}
        </div>
      ))}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!edit}>
          {t("fw.saveJails")}
        </Button>
        {edit && (
          <Button type="button" size="sm" variant="ghost" onClick={() => setEdit(null)}>
            {t("common.cancel")}
          </Button>
        )}
      </div>
    </form>
  );
}
