"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Switch } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

type State = {
  agent: boolean;
  ufw_installed: boolean;
  ufw_active: boolean;
  ufw_defaults: string;
  ufw_rules: { number: number; to: string; action: string; source: string }[];
  fail2ban_installed: boolean;
  fail2ban_running: boolean;
  jails: { name: string; banned: string[]; total_banned: number; failed: number }[];
};
const KEY = ["host-firewall"];
const select = "h-9 rounded-md border bg-card px-2 text-sm";

/** Host firewall (UFW) and fail2ban, through the host agent. Admin; changes need a fresh TOTP. */
export function FirewallDialog({ open, onOpenChange, onChanged }: { open: boolean; onOpenChange: (o: boolean) => void; onChanged: () => void }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const { data, error, isFetching } = useQuery({ queryKey: KEY, queryFn: () => api<State>("/host-firewall?fresh=true"), enabled: open });
  const [totp, setTotp] = useState<null | (() => Promise<unknown>)>(null);
  const [code, setCode] = useState("");
  const [rule, setRule] = useState({ action: "allow", port: "", protocol: "tcp", source: "any" });
  const [keepSsh, setKeepSsh] = useState(true);
  const [ban, setBan] = useState<Record<string, string>>({});
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: KEY });
    onChanged();
  };
  // Every change: if the server wants a fresh TOTP, ask for it, confirm, then retry.
  const act = useMutation({
    mutationFn: async (f: () => Promise<unknown>) => {
      try {
        return await f();
      } catch (e) {
        if (e instanceof ApiError && e.code === "totp_required") {
          setTotp(() => f);
          return null;
        }
        throw e;
      }
    },
    onSuccess: refresh,
  });
  const confirm = useMutation({
    mutationFn: async () => {
      await api("/host-firewall/confirm", { method: "POST", body: { code } });
      const retry = totp;
      setTotp(null);
      setCode("");
      if (retry) await retry();
    },
    onSuccess: refresh,
  });
  const addRule = (e: FormEvent) => {
    e.preventDefault();
    act.mutate(() => api("/host-firewall/ufw/rules", { method: "POST", body: { ...rule, port: Number(rule.port) } }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("fw.title")} description={t("fw.help")} closeLabel={t("common.close")} className="max-w-3xl">
        <div className="grid max-h-[70vh] gap-4 overflow-auto text-sm">
          <Alert tone="warn">{t("fw.dockerBypass")}</Alert>
          {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          {(act.error ?? confirm.error) && <Alert tone="danger">{errorMessage(act.error ?? confirm.error)}</Alert>}
          {totp && (
            <form
              className="flex flex-wrap items-end gap-2 rounded-md border p-3"
              onSubmit={(e) => {
                e.preventDefault();
                confirm.mutate();
              }}
            >
              <p className="w-full">{t("fw.totp")}</p>
              <Input className="w-40 font-mono" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
              <Button type="submit" size="sm" disabled={confirm.isPending}>
                {t("settings.totp.verify")}
              </Button>
            </form>
          )}

          <label className="flex items-center gap-2 font-medium">
            <Switch checked={!!data?.agent} disabled={!data || act.isPending} onChange={(e) => {
              const enabled = e.target.checked;
              if (!enabled || window.confirm(t("fw.agentConfirm"))) act.mutate(() => api("/host-firewall/agent", { method: "PUT", body: { enabled } }));
            }} />
            {t("fw.agent")}
          </label>
          <p className="-mt-2 text-xs text-muted-foreground">{t("fw.agentHelp")}</p>

          {data?.agent && (
            <>
              <section className="grid gap-2 rounded-lg border p-3">
                <h3 className="font-semibold">UFW</h3>
                {!data.ufw_installed ? (
                  <p className="text-muted-foreground">{t("fw.ufwMissing")}</p>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-3">
                      <Switch
                        checked={data.ufw_active}
                        onChange={(e) => {
                          const enabled = e.target.checked;
                          if (window.confirm(t(enabled ? "fw.enableConfirm" : "fw.disableConfirm")))
                            act.mutate(() => api("/host-firewall/ufw", { method: "PUT", body: { enabled, keep_ssh: keepSsh } }));
                        }}
                        aria-label={t("fw.ufwActive")}
                      />
                      <span>{data.ufw_active ? t("fw.active") : t("fw.inactive")}</span>
                      {data.ufw_defaults && <span className="text-xs text-muted-foreground">{data.ufw_defaults}</span>}
                      {!data.ufw_active && (
                        <label className="flex items-center gap-2 text-xs">
                          <Switch checked={keepSsh} onChange={(e) => setKeepSsh(e.target.checked)} /> {t("fw.keepSsh")}
                        </label>
                      )}
                    </div>
                    <ul className="divide-y rounded border">
                      {data.ufw_rules.map((r) => (
                        <li key={r.number} className="flex items-center gap-3 px-2 py-1 font-mono text-xs">
                          <span className="w-6 text-muted-foreground">{r.number}</span>
                          <span className="flex-1">{r.to}</span>
                          <span>{r.action}</span>
                          <span className="flex-1">{r.source}</span>
                          <Button size="sm" variant="ghost" aria-label={t("fw.deleteRule", { n: r.number })} onClick={() => window.confirm(t("fw.deleteRule", { n: r.number })) && act.mutate(() => api(`/host-firewall/ufw/rules/${r.number}`, { method: "DELETE" }))}>
                            <Trash2 className="text-danger" />
                          </Button>
                        </li>
                      ))}
                      {data.ufw_rules.length === 0 && <li className="px-2 py-1 text-xs text-muted-foreground">{t("fw.noRule")}</li>}
                    </ul>
                    <form className="flex flex-wrap items-end gap-2" onSubmit={addRule}>
                      <select className={select} value={rule.action} onChange={(e) => setRule({ ...rule, action: e.target.value })} aria-label={t("fw.action")}>
                        <option value="allow">{t("fw.allow")}</option>
                        <option value="limit">{t("fw.limit")}</option>
                        <option value="deny">{t("fw.deny")}</option>
                      </select>
                      <Input className="h-9 w-28" type="number" min={1} max={65535} required placeholder={t("fw.port")} value={rule.port} onChange={(e) => setRule({ ...rule, port: e.target.value })} aria-label={t("fw.port")} />
                      <select className={select} value={rule.protocol} onChange={(e) => setRule({ ...rule, protocol: e.target.value })} aria-label={t("fw.protocol")}>
                        <option value="tcp">TCP</option>
                        <option value="udp">UDP</option>
                        <option value="any">TCP + UDP</option>
                      </select>
                      <Input className="h-9 w-44 font-mono text-xs" placeholder={t("fw.source")} value={rule.source} onChange={(e) => setRule({ ...rule, source: e.target.value })} aria-label={t("fw.source")} />
                      <Button type="submit" size="sm" disabled={act.isPending}>
                        {t("fw.addRule")}
                      </Button>
                    </form>
                  </>
                )}
              </section>

              <section className="grid gap-2 rounded-lg border p-3">
                <h3 className="font-semibold">fail2ban</h3>
                {!data.fail2ban_installed ? (
                  <p className="text-muted-foreground">{t("fw.f2bMissing")}</p>
                ) : !data.fail2ban_running ? (
                  <p className="text-muted-foreground">{t("fw.f2bStopped")}</p>
                ) : (
                  data.jails.map((j) => (
                    <div key={j.name} className="grid gap-1 rounded border p-2">
                      <p className="font-medium">
                        {j.name} <span className="text-xs font-normal text-muted-foreground">{t("fw.jailStats", { banned: j.banned.length, total: j.total_banned, failed: j.failed })}</span>
                      </p>
                      <ul className="flex flex-wrap gap-1">
                        {j.banned.map((ip) => (
                          <li key={ip} className="flex items-center gap-1 rounded bg-danger/10 px-2 py-0.5 font-mono text-xs">
                            {ip}
                            <button className="text-muted-foreground hover:text-foreground" aria-label={t("fw.unban", { ip })} title={t("fw.unban", { ip })} onClick={() => act.mutate(() => api(`/host-firewall/fail2ban/${j.name}`, { method: "POST", body: { ip, ban: false } }))}>
                              ×
                            </button>
                          </li>
                        ))}
                      </ul>
                      <form
                        className="flex gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          act.mutate(() => api(`/host-firewall/fail2ban/${j.name}`, { method: "POST", body: { ip: ban[j.name], ban: true } }));
                        }}
                      >
                        <Input className="h-8 w-44 font-mono text-xs" required placeholder="203.0.113.5" value={ban[j.name] ?? ""} onChange={(e) => setBan({ ...ban, [j.name]: e.target.value })} aria-label={t("fw.banIp")} />
                        <Button size="sm" variant="outline" type="submit">
                          {t("fw.ban")}
                        </Button>
                      </form>
                    </div>
                  ))
                )}
              </section>
            </>
          )}
          {isFetching && <p className="text-xs text-muted-foreground">{t("common.loading")}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
