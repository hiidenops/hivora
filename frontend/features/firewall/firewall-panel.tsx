"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Switch } from "@/components/ui/input";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { ApiError, api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { LiveConnections } from "./connections";

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

/** The host firewall dialog of the topology. */
export function FirewallDialog({ open, onOpenChange, onChanged }: { open: boolean; onOpenChange: (o: boolean) => void; onChanged: () => void }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("fw.title")} description={t("fw.help")} closeLabel={t("common.close")} className="max-w-3xl">
        <div className="max-h-[70vh] overflow-auto">
          <FirewallPanel onChanged={onChanged} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Host firewall (UFW) and fail2ban, through the host agent. Admin; changes need a fresh TOTP.
 * `full` (the Firewall page) adds open ports, jail settings and routes. */
export function FirewallPanel({ onChanged, full = false }: { onChanged?: () => void; full?: boolean }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const { data, error, isFetching } = useQuery({ queryKey: KEY, queryFn: () => api<State>("/host-firewall?fresh=true") });
  const [totp, setTotp] = useState<null | (() => Promise<unknown>)>(null);
  const [code, setCode] = useState("");
  const [rule, setRule] = useState({ action: "allow", port: "", protocol: "tcp", source: "any" });
  const [keepSsh, setKeepSsh] = useState(true);
  const sourceRef = useRef<HTMLInputElement>(null);
  // From the open ports list: fill the rule form, the source is left to choose.
  const pick = (action: string, port: number, protocol: string) => {
    setRule({ action, port: String(port), protocol, source: "any" });
    sourceRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    sourceRef.current?.focus();
  };
  const [ban, setBan] = useState<Record<string, string>>({});
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: KEY });
    onChanged?.();
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

  const on = !!data?.agent;

  return (
        <div className="grid gap-4 text-sm">
          {/* The page's top: the agent's switch on the left, the Docker warning beside it. */}
          <div className="flex flex-wrap items-stretch gap-4">
            <div className={cn("surface grid content-center gap-1 rounded-lg border p-3", full && "max-w-md")}>
              <label className="flex items-center gap-2 font-medium">
                <Switch checked={!!data?.agent} disabled={!data || act.isPending} onChange={(e) => {
                  const enabled = e.target.checked;
                  if (!enabled || window.confirm(t("fw.agentConfirm"))) act.mutate(() => api("/host-firewall/agent", { method: "PUT", body: { enabled } }));
                }} />
                {t("fw.agent")}
              </label>
              <p className="text-xs text-muted-foreground">{t("fw.agentHelp")}</p>
            </div>
            <Alert tone="warn" className="flex min-w-72 flex-1 items-center">{t("fw.dockerBypass")}</Alert>
          </div>
          {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          {(act.error ?? confirm.error) && <Alert tone="danger">{errorMessage(act.error ?? confirm.error)}</Alert>}
          {totp && (
            <form
              className="surface flex flex-wrap items-end gap-2 rounded-md border p-3"
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
          {/* Who is connected first, then the rest in two columns on a wide screen. */}
          {full && on && <LiveConnections act={(f) => act.mutate(f)} />}

          {data?.agent && (
            <div className={cn("grid items-start gap-4", full && "lg:grid-cols-2")}>
              <section className="surface grid gap-2 rounded-lg border p-3">
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
                    <Table>
                      <THead>
                        <tr>
                          <Th numeric>#</Th>
                          <Th>{t("fw.to")}</Th>
                          <Th>{t("fw.action")}</Th>
                          <Th>{t("fw.from")}</Th>
                          <Th />
                        </tr>
                      </THead>
                      <TBody>
                        {data.ufw_rules.length === 0 && <TEmpty colSpan={5}>{t("fw.noRule")}</TEmpty>}
                        {data.ufw_rules.map((r) => (
                          <Tr key={r.number}>
                            <Td numeric className="text-muted-foreground">{r.number}</Td>
                            <Td mono>{r.to}</Td>
                            <Td mono>{r.action}</Td>
                            <Td mono>{r.source}</Td>
                            <Td className="py-1 text-right">
                              <Button size="sm" variant="ghost" aria-label={t("fw.deleteRule", { n: r.number })} onClick={() => window.confirm(t("fw.deleteRule", { n: r.number })) && act.mutate(() => api(`/host-firewall/ufw/rules/${r.number}`, { method: "DELETE" }))}>
                                <Trash2 className="text-danger" />
                              </Button>
                            </Td>
                          </Tr>
                        ))}
                      </TBody>
                    </Table>
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
                      <Input ref={sourceRef} className="h-9 w-44 font-mono text-xs" placeholder={t("fw.source")} value={rule.source} onChange={(e) => setRule({ ...rule, source: e.target.value })} aria-label={t("fw.source")} />
                      <Button type="submit" size="sm" disabled={act.isPending}>
                        {t("fw.addRule")}
                      </Button>
                    </form>
                  </>
                )}
              </section>

              <div className="grid gap-4">
                <section className="surface grid gap-2 rounded-lg border p-3">
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
                {full && data.fail2ban_running && <JailSettings act={(f) => act.mutate(f)} />}
              </div>
            </div>
          )}
          {full && on && (
            <div className="grid items-start gap-4 lg:grid-cols-2">
              <OpenPorts onPick={data.ufw_installed ? pick : undefined} />
              <Routes />
            </div>
          )}
          {isFetching && <p className="text-xs text-muted-foreground">{t("common.loading")}</p>}
        </div>
  );
}

type Listening = { protocol: string; address: string; port: number; process: string; app: string | null; ufw: "bypassed" | "off" | "local" | "allowed" | "blocked" };
const UFW_TONE: Record<Listening["ufw"], string> = { bypassed: "text-danger", off: "text-warn", allowed: "text-warn", local: "text-muted-foreground", blocked: "text-ok" };
const box = "surface grid gap-2 rounded-lg border p-3";

/** What listens on the host right now, and whether it is reachable from outside. */
function OpenPorts({ onPick }: { onPick?: (action: string, port: number, protocol: string) => void }) {
  const { t } = useI18n();
  const { data, error } = useQuery({ queryKey: [...KEY, "listening"], queryFn: () => api<Listening[]>("/host-firewall/listening"), refetchInterval: 5000 });
  return (
    <section className={box}>
      <h3 className="font-semibold">{t("fw.openPorts")}</h3>
      <p className="text-xs text-muted-foreground">{t("fw.openPortsHelp")}</p>
      {error && <Alert tone="danger">{String(error)}</Alert>}
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.port")}</Th>
            <Th>{t("fw.address")}</Th>
            <Th>{t("fw.process")}</Th>
            <Th>{t("fw.reach")}</Th>
            {onPick && <Th />}
          </tr>
        </THead>
        <TBody>
          {data?.length === 0 && <TEmpty colSpan={onPick ? 5 : 4}>{t("fw.noOpenPort")}</TEmpty>}
          {data?.map((p) => (
            <Tr key={`${p.protocol}${p.address}${p.port}`}>
              <Td mono>
                {p.port}/{p.protocol}
              </Td>
              <Td mono>{p.address}</Td>
              <Td>{p.app ? t("fw.dockerApp", { app: p.app }) : p.process || "—"}</Td>
              <Td className={UFW_TONE[p.ufw]}>{t(`fw.reach.${p.ufw}`)}</Td>
              {onPick && (
                <Td className="whitespace-nowrap py-1 text-right">
                  {p.ufw !== "local" && (
                    <>
                      <Button size="sm" variant="ghost" disabled={p.ufw === "bypassed"} title={p.ufw === "bypassed" ? t("fw.pickBypassed") : undefined} onClick={() => onPick("allow", p.port, p.protocol)}>
                        {t("fw.allow")}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={p.ufw === "bypassed"} title={p.ufw === "bypassed" ? t("fw.pickBypassed") : undefined} onClick={() => onPick("deny", p.port, p.protocol)}>
                        {t("fw.deny")}
                      </Button>
                    </>
                  )}
                </Td>
              )}
            </Tr>
          ))}
        </TBody>
      </Table>
    </section>
  );
}

type Jail = { maxretry: string; bantime: string; findtime: string };

/** maxretry / bantime / findtime per jail, written to jail.d/hivora.local then reloaded. */
function JailSettings({ act }: { act: (f: () => Promise<unknown>) => void }) {
  const { t } = useI18n();
  const { data } = useQuery({ queryKey: [...KEY, "jails"], queryFn: () => api<Record<string, Jail>>("/host-firewall/fail2ban/settings") });
  const [edit, setEdit] = useState<Record<string, Jail> | null>(null);
  const jails = edit ?? data ?? {};
  const set = (name: string, key: keyof Jail, value: string) => setEdit({ ...jails, [name]: { ...jails[name], [key]: value } });
  const save = (e: FormEvent) => {
    e.preventDefault();
    const body = Object.fromEntries(
      Object.entries(jails).map(([name, j]) => [name, { maxretry: Number(j.maxretry) || null, bantime: j.bantime || null, findtime: j.findtime || null }]),
    );
    act(async () => {
      await api("/host-firewall/fail2ban/settings", { method: "PUT", body: { jails: body } });
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

type Route = { dst: string; gateway: string | null; dev: string; protocol: string | null; scope: string | null; prefsrc: string | null; metric: number | null };
type Forward = { port: number; protocol: string; address: string; app: string; container_port: number };

/** Host routing table and Docker port forwards (read-only). */
function Routes() {
  const { t } = useI18n();
  const { data } = useQuery({ queryKey: [...KEY, "routes"], queryFn: () => api<{ routes: Route[]; forwards: Forward[] }>("/host-firewall/routes") });
  return (
    <section className={box}>
      <h3 className="font-semibold">{t("fw.routes")}</h3>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.route.dst")}</Th>
            <Th>{t("fw.route.gateway")}</Th>
            <Th>{t("fw.route.dev")}</Th>
            <Th>{t("fw.route.src")}</Th>
            <Th numeric>{t("fw.route.metric")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.routes.map((r, i) => (
            <Tr key={i}>
              <Td mono>{r.dst}</Td>
              <Td mono>{r.gateway ?? "—"}</Td>
              <Td mono>{r.dev}</Td>
              <Td mono>{r.prefsrc ?? "—"}</Td>
              <Td numeric mono>{r.metric ?? "—"}</Td>
            </Tr>
          ))}
        </TBody>
      </Table>
      <h3 className="mt-2 font-semibold">{t("fw.forwards")}</h3>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.forward.host")}</Th>
            <Th>{t("fw.forward.app")}</Th>
            <Th numeric>{t("fw.forward.container")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.forwards.length === 0 && <TEmpty colSpan={3}>{t("fw.noForward")}</TEmpty>}
          {data?.forwards.map((f) => (
            <Tr key={`${f.address}${f.port}${f.protocol}`}>
              <Td mono>
                {f.address}:{f.port}/{f.protocol}
              </Td>
              <Td>{f.app}</Td>
              <Td numeric mono>{f.container_port}</Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </section>
  );
}
