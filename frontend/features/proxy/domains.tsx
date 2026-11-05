"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Lock, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Proxy = components["schemas"]["ProxyOut"];
type Route = Proxy["routes"][number];
type Dns = components["schemas"]["DnsOut"];

const PROXY = ["proxy"];
const STATUS = { valid: "bg-ok/15 text-ok", pending: "bg-warn/15 text-warn", error: "bg-danger/15 text-danger" } as Record<string, string>;

export const useProxy = () => useQuery({ queryKey: PROXY, queryFn: () => api<Proxy>("/proxy"), refetchInterval: 30_000 });

/** One public domain: its certificate (Caddy's), where its DNS points, why it fails. */
function DomainRow({ r, publicIp }: { r: Route; publicIp: string | null }) {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const remove = useMutation({ mutationFn: () => api(`/proxy/routes/${r.id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: PROXY }) });
  return (
    <li className="grid gap-1 rounded-md border px-2 py-1.5">
      <div className="flex items-center gap-2">
        <Lock className="size-3.5 text-muted-foreground" />
        <a href={`https://${r.domain}`} target="_blank" rel="noopener noreferrer" className="font-mono text-xs hover:underline">
          {r.domain}
        </a>
        <span className="text-xs text-muted-foreground">→ {r.app_name}</span>
        <span className={cn("ml-auto rounded px-1.5 text-[10px] leading-5", STATUS[r.status])}>{t(`proxy.status.${r.status}` as "proxy.status.valid")}</span>
        <Button size="sm" variant="ghost" className="h-7 px-2" aria-label={t("proxy.delete", { domain: r.domain })} loading={remove.isPending} onClick={() => window.confirm(t("proxy.deleteConfirm", { domain: r.domain })) && remove.mutate()}>
          <Trash2 className="text-danger" />
        </Button>
      </div>
      {r.expires_at && <p className="text-xs text-muted-foreground">{t("proxy.expires", { date: new Date(r.expires_at).toLocaleDateString(lang), issuer: r.issuer ?? "" })}</p>}
      {!r.served && <p className="text-xs text-danger">{t("proxy.notServed")}</p>}
      {!r.points_here && <p className="text-xs text-warn">{r.dns.length ? t("proxy.dnsElsewhere", { ips: r.dns.join(", "), ip: publicIp ?? "?" }) : t("proxy.dnsNone", { ip: publicIp ?? "?" })}</p>}
      {r.status === "error" && r.error && <p className="break-words font-mono text-[11px] text-danger">{r.error}</p>}
    </li>
  );
}

/** Give a domain to one of ``apps``: a public one (HTTPS proxy) or a VPN name. */
function AddName({ apps, placeholder, submit, pending, error }: { apps: { id: number; name: string }[]; placeholder: string; submit: (name: string, appId: number, done: () => void) => void; pending: boolean; error: unknown }) {
  const { t, errorMessage } = useI18n();
  const [name, setName] = useState("");
  const [app, setApp] = useState("");
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(name, Number(app), () => setName(""));
  };
  if (apps.length === 0) return <p className="text-xs text-muted-foreground">{t("names.noApp")}</p>;
  return (
    <form className="grid gap-2" onSubmit={onSubmit}>
      <div className="flex flex-wrap gap-2">
        <Input className="h-8 min-w-0 flex-1 font-mono text-xs" aria-label={t("names.name")} placeholder={placeholder} value={name} maxLength={253} required onChange={(e) => setName(e.target.value)} />
        <Select className="h-8 w-36 text-xs" aria-label={t("names.app")} value={app} required onChange={(e) => setApp(e.target.value)}>
          <option value="" disabled>
            {t("names.app")}
          </option>
          {apps.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Button type="submit" size="sm" className="h-8" loading={pending} disabled={pending}>
          {t("names.add")}
        </Button>
      </div>
      {Boolean(error) && <Alert tone="danger">{errorMessage(error)}</Alert>}
    </form>
  );
}

function useAddDomain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ domain, appId }: { domain: string; appId: number }) => api<{ id: number; job: number | null }>("/proxy/routes", { method: "POST", body: { domain, app_id: appId } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: PROXY }),
  });
}

/** The proxy app's page: every public domain and its certificate. */
export function ProxyCard() {
  const { t, errorMessage } = useI18n();
  const { data, error } = useProxy();
  const add = useAddDomain();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-4" /> {t("proxy.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
        <p className="text-xs text-muted-foreground">{t("proxy.help", { ip: data?.public_ip ?? "?" })}</p>
        <ul className="grid gap-1.5">
          {data?.routes.length === 0 && <li className="text-muted-foreground">{t("proxy.empty")}</li>}
          {data?.routes.map((r) => <DomainRow key={r.id} r={r} publicIp={data.public_ip} />)}
        </ul>
        {data && <AddName apps={data.targets} placeholder="cloud.exemple.fr" pending={add.isPending} error={add.error} submit={(domain, appId, done) => add.mutate({ domain, appId }, { onSuccess: done })} />}
      </CardContent>
    </Card>
  );
}

/** A zone's overview: its apps' names. Behind a VPN, names of the VPN's DNS (nas.lan);
 *  otherwise public domains, HTTPS through the proxy (installed from here if missing). */
export function ZoneNames({ zone, vpnId }: { zone: string; vpnId: number | null }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-2 border-t pt-3">
      <p className="text-xs font-medium">{t(vpnId ? "names.local" : "names.public")}</p>
      {vpnId ? <LocalNames zone={zone} vpnId={vpnId} /> : <PublicNames zone={zone} />}
      <p className="text-[11px] text-muted-foreground">{t(vpnId ? "names.localHelp" : "names.publicHelp")}</p>
    </div>
  );
}

function LocalNames({ zone, vpnId }: { zone: string; vpnId: number }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const key = ["vpn-dns", vpnId];
  const { data } = useQuery({ queryKey: key, queryFn: () => api<Dns>(`/apps/${vpnId}/vpn/dns`) });
  const add = useMutation({ mutationFn: ({ name, appId }: { name: string; appId: number }) => api(`/apps/${vpnId}/vpn/dns`, { method: "POST", body: { name, app_id: appId } }), onSuccess: () => qc.invalidateQueries({ queryKey: key }) });
  const remove = useMutation({ mutationFn: (id: number) => api(`/apps/${vpnId}/vpn/dns/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: key }) });
  if (!data) return null;
  const apps = data.targets.filter((a) => a.zone === zone);
  const records = data.records.filter((r) => apps.some((a) => a.id === r.app_id));
  return (
    <>
      {!data.enabled && <Alert tone="warn">{t("dns.disabled")}</Alert>}
      <ul className="grid gap-1 text-xs">
        {records.map((r) => (
          <li key={r.id} className="flex items-center gap-2">
            <span className="font-mono">{r.name}</span>
            <span className="text-muted-foreground">→ {r.app_name}</span>
            <Button size="sm" variant="ghost" className="ml-auto h-6 px-1.5" aria-label={t("dns.delete", { name: r.name })} onClick={() => remove.mutate(r.id)}>
              <Trash2 className="text-danger" />
            </Button>
          </li>
        ))}
      </ul>
      <AddName apps={apps} placeholder="nas.lan" pending={add.isPending} error={add.error} submit={(name, appId, done) => add.mutate({ name, appId }, { onSuccess: done })} />
    </>
  );
}

function PublicNames({ zone }: { zone: string }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const { data } = useProxy();
  const add = useAddDomain();
  const install = useMutation({ mutationFn: () => api("/apps", { method: "POST", body: { template: "caddy", name: "proxy" } }), onSuccess: () => qc.invalidateQueries({ queryKey: PROXY }) });
  if (!data) return null;
  if (!data.installed)
    return (
      <div className="grid gap-2">
        <p className="text-xs text-muted-foreground">{t("names.installHelp")}</p>
        <Button size="sm" className="justify-self-start" loading={install.isPending} disabled={install.isPending || install.isSuccess} onClick={() => install.mutate()}>
          {t(install.isSuccess ? "names.installing" : "names.install")}
        </Button>
        {install.error && <Alert tone="danger">{errorMessage(install.error)}</Alert>}
      </div>
    );
  return (
    <>
      <ul className="grid gap-1">
        {data.routes
          .filter((r) => r.zone === zone)
          .map((r) => (
            <DomainRow key={r.id} r={r} publicIp={data.public_ip} />
          ))}
      </ul>
      <AddName apps={data.targets.filter((a) => a.zone === zone)} placeholder="cloud.exemple.fr" pending={add.isPending} error={add.error} submit={(domain, appId, done) => add.mutate({ domain, appId }, { onSuccess: done })} />
      {add.data?.job != null && <p className="text-[11px] text-muted-foreground">{t("names.joining")}</p>}
    </>
  );
}
