"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, History, KeyRound, Lock, Megaphone, Server, Settings2, ShieldAlert, UserX, Users, X } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";

import { useSession } from "@/components/app-shell";
import { CollapsibleCard } from "@/components/collapsible-card";
import { useConfirmed } from "@/components/totp-form";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Select, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, THead, Th, Tr } from "@/components/ui/table";
import { CopyAddress } from "@/features/apps/status-hero";
import { api, type TsAdminKey, type TsBan, type TsClient, type TsInfo, type TsJail, type TsLogEntry } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

// Under keys.game: refreshed with the app's other views when its state changes.
const tsKey = (appId: number, ...rest: string[]) => [...keys.game(appId), "ts", ...rest];
const DURATIONS = [60, 1440, 10080, 0]; // minutes; 0: forever

function useTs<T>(appId: number, path: string, enabled: boolean, poll = false) {
  return useQuery({
    queryKey: tsKey(appId, path),
    queryFn: () => api<T>(`/apps/${appId}/teamspeak${path}`),
    enabled,
    refetchInterval: poll && enabled ? 15_000 : false,
  });
}

function useTsChange<A>(appId: number, call: (arg: A) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSettled: () => qc.invalidateQueries({ queryKey: tsKey(appId) }),
  });
}

function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={`px-3 py-2 ${className ?? ""}`}>{children}</td>;
}

/** A TeamSpeak 3 server's own panel (template ``teamspeak``): its ServerQuery, from Hivora. */
export function TeamSpeakPanel({ appId, running }: { appId: number; running: boolean }) {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const info = useTs<TsInfo>(appId, "", running, true);
  if (!running) {
    return (
      <CollapsibleCard storageKey="ts.server" defaultOpen title={<><Server className="size-5" /> {t("ts.server")}</>}>
        <p className="text-sm text-muted-foreground">{t("ts.offline")}</p>
      </CollapsibleCard>
    );
  }
  return (
    <>
      <ServerCard appId={appId} info={info.data} error={info.error ? errorMessage(info.error) : null} />
      <ClientsCard appId={appId} />
      {can("admin") && <AdminKeyCard appId={appId} />}
      <BansCard appId={appId} />
      <HistoryCard appId={appId} info={info.data} />
      {can("admin") && <JailCard appId={appId} />}
    </>
  );
}

function ServerCard({ appId, info, error }: { appId: number; info?: TsInfo; error: string | null }) {
  const { t } = useI18n();
  const { can } = useSession();
  const [open, setOpen] = useState<"settings" | "password" | "message" | null>(null);
  return (
    <CollapsibleCard
      storageKey="ts.server"
      defaultOpen
      title={<><Server className="size-5" /> {t("ts.server")}</>}
      aside={info && <span className="text-sm font-medium tabular-nums">{t("mc.online", { online: info.online, max: info.max_clients })}</span>}
    >
      {error && <Alert tone="danger">{error}</Alert>}
      {!info && !error && <Skeleton className="h-16" />}
      {info && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("ts.name")}</dt>
          <dd className="truncate font-medium">{info.name}</dd>
          <dt className="text-muted-foreground">{t("ts.password")}</dt>
          <dd>{info.password ? t("ts.passwordSet") : t("ts.passwordNone")}</dd>
          <dt className="text-muted-foreground">{t("ts.version")}</dt>
          <dd className="font-mono text-xs leading-5">{info.version}</dd>
        </dl>
      )}
      {info && can("operator") && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => setOpen("settings")}>
            <Settings2 /> {t("ts.settings")}
          </Button>
          {can("admin") && (
            <Button size="sm" variant="outline" onClick={() => setOpen("password")}>
              <Lock /> {t("ts.changePassword")}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setOpen("message")}>
            <Megaphone /> {t("ts.message")}
          </Button>
        </div>
      )}
      {info && open === "settings" && <SettingsDialog appId={appId} info={info} onClose={() => setOpen(null)} />}
      {info && open === "password" && <PasswordDialog appId={appId} info={info} onClose={() => setOpen(null)} />}
      {open === "message" && <MessageDialog appId={appId} onClose={() => setOpen(null)} />}
    </CollapsibleCard>
  );
}

function SettingsDialog({ appId, info, onClose }: { appId: number; info: TsInfo; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const [form, setForm] = useState({ name: info.name, welcome: info.welcome, max_clients: info.max_clients, log_clients: info.log_clients });
  const save = useTsChange(appId, () => api(`/apps/${appId}/teamspeak`, { method: "PUT", body: form }));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t("ts.settings")} closeLabel={t("common.close")}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(undefined, { onSuccess: onClose });
          }}
        >
          <Label className="grid gap-1">
            {t("ts.name")}
            <Input required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Label>
          <Label className="grid gap-1">
            {t("ts.welcome")}
            <textarea
              className="min-h-20 rounded-md border bg-background px-3 py-2 text-sm"
              maxLength={1024}
              value={form.welcome}
              onChange={(e) => setForm({ ...form, welcome: e.target.value })}
            />
          </Label>
          <Label className="grid gap-1">
            {t("ts.slots")}
            <Input type="number" min={1} max={32} required className="w-28" value={form.max_clients} onChange={(e) => setForm({ ...form, max_clients: Number(e.target.value) })} />
            <span className="text-xs font-normal text-muted-foreground">{t("ts.slotsHelp")}</span>
          </Label>
          <Label className="flex items-center gap-2">
            <Switch checked={form.log_clients} onChange={(e) => setForm({ ...form, log_clients: e.target.checked })} />
            {t("ts.logClients")}
          </Label>
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          <Button type="submit" loading={save.isPending} className="justify-self-end">
            {t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PasswordDialog({ appId, info, onClose }: { appId: number; info: TsInfo; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const save = useConfirmed(
    (value: string) => api(`/apps/${appId}/teamspeak/password`, { method: "PUT", body: { password: value } }),
    () => {
      void qc.invalidateQueries({ queryKey: tsKey(appId) });
      onClose();
    },
  );
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t("ts.changePassword")} description={t("ts.passwordHelp")} closeLabel={t("common.close")}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.run(password);
          }}
        >
          <Label className="grid gap-1">
            {t("ts.newPassword")}
            <Input type="password" autoComplete="new-password" required maxLength={64} value={password} onChange={(e) => setPassword(e.target.value)} />
          </Label>
          {save.totp}
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          <div className="flex flex-wrap justify-end gap-2">
            {info.password && (
              <Button type="button" variant="outline" disabled={save.isPending} onClick={() => save.run("")}>
                {t("ts.removePassword")}
              </Button>
            )}
            <Button type="submit" loading={save.isPending}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MessageDialog({ appId, onClose }: { appId: number; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const [text, setText] = useState("");
  const send = useTsChange(appId, () => api(`/apps/${appId}/teamspeak/message`, { method: "POST", body: { text } }));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t("ts.message")} description={t("ts.messageHelp")} closeLabel={t("common.close")}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate(undefined, { onSuccess: onClose });
          }}
        >
          <textarea
            aria-label={t("ts.message")}
            className="min-h-24 rounded-md border bg-background px-3 py-2 text-sm"
            required
            maxLength={1024}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {send.error && <Alert tone="danger">{errorMessage(send.error)}</Alert>}
          <Button type="submit" loading={send.isPending} className="justify-self-end">
            <Megaphone /> {t("ts.send")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BanDialog({ appId, target, onClose }: { appId: number; target: { clid?: number; ip?: string; label: string }; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const [minutes, setMinutes] = useState(1440);
  const [reason, setReason] = useState("");
  const ban = useTsChange(appId, () =>
    api(`/apps/${appId}/teamspeak/bans`, { method: "POST", body: { clid: target.clid ?? null, ip: target.ip ?? null, minutes, reason } }),
  );
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t("ts.banTitle", { name: target.label })} closeLabel={t("common.close")}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            ban.mutate(undefined, { onSuccess: onClose });
          }}
        >
          <Label className="grid gap-1">
            {t("ts.duration")}
            <Select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
              {DURATIONS.map((m) => (
                <option key={m} value={m}>
                  {t(`ts.duration.${m}` as "ts.duration.0")}
                </option>
              ))}
            </Select>
          </Label>
          <Label className="grid gap-1">
            {t("ts.reason")}
            <Input maxLength={80} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Label>
          {ban.error && <Alert tone="danger">{errorMessage(ban.error)}</Alert>}
          <Button type="submit" variant="destructive" loading={ban.isPending} className="justify-self-end">
            <Ban /> {t("ts.ban")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ClientsCard({ appId }: { appId: number }) {
  const { t, lang, errorMessage } = useI18n();
  const { can } = useSession();
  const clients = useTs<TsClient[]>(appId, "/clients", true, true);
  const [banning, setBanning] = useState<TsClient | null>(null);
  const kick = useTsChange(appId, (clid: number) => api(`/apps/${appId}/teamspeak/clients/${clid}/kick`, { method: "POST", body: { reason: "" } }));
  return (
    <CollapsibleCard storageKey="ts.clients" defaultOpen title={<><Users className="size-5" /> {t("ts.clients")}</>}>
      {clients.error && <Alert tone="danger">{errorMessage(clients.error)}</Alert>}
      {kick.error && <Alert tone="danger">{errorMessage(kick.error)}</Alert>}
      {clients.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("mc.nobody")}</p>}
      {!!clients.data?.length && (
        <Table>
          <THead>
            <tr>
              <Th>{t("ts.nickname")}</Th>
              <Th>{t("ts.address")}</Th>
              <Th>{t("ts.since")}</Th>
              {can("operator") && <Th />}
            </tr>
          </THead>
          <TBody>
            {clients.data.map((c) => (
              <Tr key={c.clid}>
                <Td className="font-medium">
                  {c.name} {c.country && <span className="text-xs text-muted-foreground">{c.country}</span>}
                </Td>
                <Td className="font-mono text-xs">{c.ip ?? "—"}</Td>
                <Td className="text-xs text-muted-foreground">{c.connected_at ? new Date(c.connected_at * 1000).toLocaleTimeString(lang) : "—"}</Td>
                {can("operator") && (
                  <Td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" title={t("ts.kick")} aria-label={t("ts.kickName", { name: c.name })} disabled={kick.isPending} onClick={() => kick.mutate(c.clid)}>
                      <UserX />
                    </Button>
                    <Button size="sm" variant="ghost" title={t("ts.ban")} aria-label={t("ts.banTitle", { name: c.name })} onClick={() => setBanning(c)}>
                      <Ban />
                    </Button>
                  </Td>
                )}
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      {banning && <BanDialog appId={appId} target={{ clid: banning.clid, label: banning.name }} onClose={() => setBanning(null)} />}
    </CollapsibleCard>
  );
}

function AdminKeyCard({ appId }: { appId: number }) {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const pending = useTs<TsAdminKey[]>(appId, "/admin-keys", true);
  const [key, setKey] = useState<string | null>(null);
  const renew = useConfirmed(
    () => api<{ key: string }>(`/apps/${appId}/teamspeak/admin-keys`, { method: "POST" }),
    (r) => {
      setKey(r.key);
      void qc.invalidateQueries({ queryKey: tsKey(appId, "/admin-keys") });
    },
  );
  return (
    <CollapsibleCard storageKey="ts.adminKey" title={<><KeyRound className="size-5" /> {t("ts.adminKey")}</>}>
      <p className="text-sm text-muted-foreground">{t("ts.adminKeyHelp")}</p>
      {pending.data && (
        <p className="text-sm">
          {pending.data.length === 0
            ? t("ts.noPendingKey")
            : t("ts.pendingKeys", { n: pending.data.length, date: new Date(Math.max(...pending.data.map((k) => k.created)) * 1000).toLocaleString(lang) })}
        </p>
      )}
      {key && (
        <Alert className="grid gap-2">
          <span>{t("ts.keyOnce")}</span>
          <CopyAddress value={key} />
        </Alert>
      )}
      {renew.totp}
      {renew.error && <Alert tone="danger">{errorMessage(renew.error)}</Alert>}
      <Button size="sm" className="justify-self-start" loading={renew.isPending} onClick={() => renew.run(undefined)}>
        <KeyRound /> {t("ts.newKey")}
      </Button>
    </CollapsibleCard>
  );
}

function BansCard({ appId }: { appId: number }) {
  const { t, lang, errorMessage } = useI18n();
  const { can } = useSession();
  const bans = useTs<TsBan[]>(appId, "/bans", true);
  const [ip, setIp] = useState("");
  const [banning, setBanning] = useState<string | null>(null);
  const unban = useTsChange(appId, (id: number) => api(`/apps/${appId}/teamspeak/bans/${id}`, { method: "DELETE" }));
  const until = (b: TsBan) => (b.duration_s === 0 ? t("ts.duration.0") : new Date((b.created + b.duration_s) * 1000).toLocaleString(lang));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBanning(ip.trim());
    setIp("");
  };
  return (
    <CollapsibleCard
      storageKey="ts.bans"
      title={<><Ban className="size-5" /> {t("ts.bans")}</>}
      aside={!!bans.data?.length && <span className="text-sm tabular-nums">{bans.data.length}</span>}
    >
      {bans.error && <Alert tone="danger">{errorMessage(bans.error)}</Alert>}
      {unban.error && <Alert tone="danger">{errorMessage(unban.error)}</Alert>}
      {bans.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("ts.noBan")}</p>}
      {!!bans.data?.length && (
        <Table>
          <THead>
            <tr>
              <Th>{t("ts.target")}</Th>
              <Th>{t("ts.reason")}</Th>
              <Th>{t("ts.until")}</Th>
              {can("operator") && <Th />}
            </tr>
          </THead>
          <TBody>
            {bans.data.map((b) => (
              <Tr key={b.id}>
                <Td className="font-mono text-xs">{b.ip ?? b.name ?? b.uid ?? "—"}</Td>
                <Td className="text-xs">{b.reason || "—"}</Td>
                <Td className="text-xs text-muted-foreground">{until(b)}</Td>
                {can("operator") && (
                  <Td className="text-right">
                    <Button size="sm" variant="ghost" aria-label={t("ts.unban", { name: b.ip ?? b.name ?? String(b.id) })} disabled={unban.isPending} onClick={() => unban.mutate(b.id)}>
                      <X />
                    </Button>
                  </Td>
                )}
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      {can("operator") && (
        <form onSubmit={submit} className="flex gap-2">
          <Input aria-label={t("ts.banIp")} placeholder={t("ts.banIp")} className="w-56 font-mono" required maxLength={45} value={ip} onChange={(e) => setIp(e.target.value)} />
          <Button type="submit" size="sm" variant="outline">
            <Ban /> {t("ts.ban")}
          </Button>
        </form>
      )}
      {banning && <BanDialog appId={appId} target={{ ip: banning, label: banning }} onClose={() => setBanning(null)} />}
    </CollapsibleCard>
  );
}

function HistoryCard({ appId, info }: { appId: number; info?: TsInfo }) {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const history = useTs<TsLogEntry[]>(appId, "/history", true);
  const [banning, setBanning] = useState<string | null>(null);
  const enable = useTsChange(appId, () =>
    api(`/apps/${appId}/teamspeak`, { method: "PUT", body: { name: info!.name, welcome: info!.welcome, max_clients: info!.max_clients, log_clients: true } }),
  );
  return (
    <CollapsibleCard storageKey="ts.history" title={<><History className="size-5" /> {t("ts.history")}</>}>
      {info && !info.log_clients && (
        <Alert tone="warn" className="flex flex-wrap items-center justify-between gap-2">
          {t("ts.logOff")}
          {can("operator") && (
            <Button size="sm" variant="outline" loading={enable.isPending} onClick={() => enable.mutate(undefined)}>
              {t("ts.logOn")}
            </Button>
          )}
        </Alert>
      )}
      {history.error && <Alert tone="danger">{errorMessage(history.error)}</Alert>}
      {history.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("ts.noHistory")}</p>}
      <ul className="grid gap-1 text-sm">
        {history.data?.map((e, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{e.ts.slice(0, 19)}</span>
            <Badge>{t(`ts.event.${e.event}` as "ts.event.connected")}</Badge>
            {e.name && <span className="font-medium">{e.name}</span>}
            {e.ip && <span className="font-mono text-xs">{e.ip}</span>}
            {e.reason && <span className="text-xs text-muted-foreground">{e.reason}</span>}
            {e.ip && e.event === "connected" && can("operator") && (
              <Button size="sm" variant="ghost" className="h-7 px-2" aria-label={t("ts.banTitle", { name: e.ip })} onClick={() => setBanning(e.ip)}>
                <Ban />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {banning && <BanDialog appId={appId} target={{ ip: banning, label: banning }} onClose={() => setBanning(null)} />}
    </CollapsibleCard>
  );
}

function JailCard({ appId }: { appId: number }) {
  const { t, errorMessage } = useI18n();
  const jail = useTs<TsJail>(appId, "/jail", true);
  const [draft, setDraft] = useState<TsJail["settings"] | null>(null);
  const settings = draft ?? jail.data?.settings;
  const save = useTsChange(appId, (enabled: boolean) => api(`/apps/${appId}/teamspeak/jail`, { method: "PUT", body: { enabled, settings } }));
  const unban = useTsChange(appId, (ip: string) => api(`/apps/${appId}/teamspeak/jail/unban`, { method: "POST", body: { ip } }));
  const data = jail.data;
  return (
    <CollapsibleCard
      storageKey="ts.jail"
      title={<><ShieldAlert className="size-5" /> {t("ts.jail")}</>}
      aside={data?.enabled && <Badge>{t("ts.jailOn")}</Badge>}
    >
      <p className="text-sm text-muted-foreground">{t("ts.jailHelp")}</p>
      {jail.error && <Alert tone="danger">{errorMessage(jail.error)}</Alert>}
      {data && !data.agent && (
        <Alert tone="warn">
          {t("ts.jailAgent")}{" "}
          <Link href="/firewall/" className="underline underline-offset-2">
            {t("host.agentLink")}
          </Link>
        </Alert>
      )}
      {data?.agent && settings && (
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(true, { onSuccess: () => setDraft(null) });
          }}
        >
          <div className="flex flex-wrap gap-3">
            <Label className="grid gap-1">
              {t("ts.maxretry")}
              <Input type="number" min={1} max={1000} className="w-24" value={settings.maxretry} onChange={(e) => setDraft({ ...settings, maxretry: Number(e.target.value) })} />
            </Label>
            <Label className="grid gap-1">
              {t("ts.findtime")}
              <Input className="w-24 font-mono" pattern="-?\d{1,9}[smhdw]?" value={settings.findtime} onChange={(e) => setDraft({ ...settings, findtime: e.target.value })} />
            </Label>
            <Label className="grid gap-1">
              {t("ts.bantime")}
              <Input className="w-24 font-mono" pattern="-?\d{1,9}[smhdw]?" value={settings.bantime} onChange={(e) => setDraft({ ...settings, bantime: e.target.value })} />
            </Label>
          </div>
          {data.enabled && data.matched !== null && data.matched !== undefined && <p className="text-xs text-muted-foreground">{t("ts.matched", { n: data.matched })}</p>}
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="sm" loading={save.isPending}>
              {data.enabled ? t("common.save") : t("ts.jailEnable")}
            </Button>
            {data.enabled && (
              <Button type="button" size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate(false)}>
                {t("ts.jailDisable")}
              </Button>
            )}
          </div>
        </form>
      )}
      {data?.enabled && data.banned.length > 0 && (
        <div className="grid gap-2">
          <h4 className="text-sm font-medium">{t("ts.jailBanned", { n: data.banned.length })}</h4>
          <ul className="flex flex-wrap gap-2">
            {data.banned.map((ip) => (
              <li key={ip}>
                <Badge className="gap-1 py-1 pr-1 font-mono text-xs">
                  {ip}
                  <button className="rounded p-0.5 hover:bg-muted" aria-label={t("ts.unban", { name: ip })} disabled={unban.isPending} onClick={() => unban.mutate(ip)}>
                    <X className="size-3.5" />
                  </button>
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </CollapsibleCard>
  );
}
