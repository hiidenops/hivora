"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, KeyRound, Plus, QrCode, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Switch } from "@/components/ui/input";
import { units } from "@/features/activity/host-charts";
import { api, type JobRef } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { keys, useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Vpn = components["schemas"]["VpnOut"];
type Client = components["schemas"]["VpnClientOut"];

const ips = (text: string) => text.split(/[\s,]+/).filter(Boolean);

type Zone = { slug: string; name: string; color: string };
type Routing = Client["routing"];

/** "2026-09-28T14:00:00+00:00" <-> the value of <input type="datetime-local"> (local time). */
const toLocal = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

function ClientSettings({ appId, client, vpn, zones, onSaved }: { appId: number; client: Client; vpn: Vpn; zones: Zone[]; onSaved: () => void }) {
  const { t, errorMessage } = useI18n();
  const [name, setName] = useState(client.name);
  const [address, setAddress] = useState(client.address ?? "");
  const [access, setAccess] = useState(client.access);
  const [routing, setRouting] = useState<Routing>(client.routing);
  const [custom, setCustom] = useState((client.allowed_ips ?? []).join(", "));
  const [expires, setExpires] = useState(toLocal(client.expires_at));
  const save = useMutation({
    mutationFn: () =>
      api(`/apps/${appId}/vpn/clients/${client.id}`, {
        method: "PUT",
        body: {
          name,
          address: address.trim() || null,
          access,
          routing,
          ...(routing === "custom" ? { allowed_ips: ips(custom) } : {}),
          expires_at: expires ? new Date(expires).toISOString() : null,
        },
      }),
    onSuccess: onSaved,
  });
  const reached = zones.filter((z) => vpn.zones.includes(z.slug));
  const toggleZone = (slug: string, on: boolean) =>
    setAccess({ ...access, zones: on ? [...access.zones, slug] : access.zones.filter((z) => z !== slug) });
  return (
    <details className="group rounded-md border bg-muted/30 px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium">{t("vpn.settings")}</summary>
      <form
        className="mt-3 grid gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="flex flex-wrap gap-3">
          <label className="grid gap-1 text-sm">
            {t("vpn.name")}
            <Input className="h-8 w-48" value={name} maxLength={32} pattern="[A-Za-z0-9 _.\-]+" required onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="grid gap-1 text-sm">
            {t("vpn.address")}
            <Input className="h-8 w-36 font-mono text-xs" value={address} maxLength={15} onChange={(e) => setAddress(e.target.value)} />
          </label>
          <label className="grid gap-1 text-sm">
            {t("vpn.expires")}
            <Input type="datetime-local" className="h-8 w-56" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
        </div>
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">{t("vpn.access")}</legend>
          <p className="text-xs text-muted-foreground">{t("vpn.accessHelp")}</p>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <Switch checked={access.internet} onChange={(e) => setAccess({ ...access, internet: e.target.checked })} /> {t("vpn.accessInternet")}
            </label>
            <label className="flex items-center gap-2">
              <Switch checked={access.lan} onChange={(e) => setAccess({ ...access, lan: e.target.checked })} /> {t("vpn.accessLan")}
            </label>
            {reached.map((z) => (
              <label key={z.slug} className="flex items-center gap-2">
                <Switch checked={access.zones.includes(z.slug)} onChange={(e) => toggleZone(z.slug, e.target.checked)} />
                <span className="size-2.5 rounded-full" style={{ background: z.color }} /> {z.name}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="grid gap-1 text-sm">
          {t("vpn.routing")}
          <select className="h-9 rounded-md border bg-card px-2 text-sm" value={routing} onChange={(e) => setRouting(e.target.value as Routing)}>
            <option value="default">{t("vpn.routing.default", { ips: vpn.default_allowed_ips })}</option>
            <option value="all">{t("vpn.routing.all")}</option>
            <option value="access">{t("vpn.routing.access")}</option>
            <option value="custom">{t("vpn.routing.custom")}</option>
          </select>
        </label>
        {routing === "custom" && (
          <Input aria-label={t("vpn.allowedIps")} className="h-8 font-mono text-xs" placeholder="192.168.1.0/24, 10.8.0.0/24" value={custom} required onChange={(e) => setCustom(e.target.value)} />
        )}
        <Button type="submit" size="sm" className="justify-self-start" disabled={save.isPending}>
          {t("common.save")}
        </Button>
        {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      </form>
    </details>
  );
}

/** Clients of the WireGuard server and the zones it reaches: Hivora writes its config. */
export function VpnCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const key = keys.vpn(appId);
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Vpn>(`/apps/${appId}/vpn`), refetchInterval: 15_000 });
  const { data: zones } = useZones();
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[] | null>(null);
  const u = units(lang);

  const act = useMutation({
    mutationFn: (f: () => Promise<unknown>) => f(),
    onSuccess: refresh,
  });
  const saveZones = useMutation({
    mutationFn: (list: string[]) => api<JobRef>(`/apps/${appId}/vpn/zones`, { method: "PUT", body: { zones: list } }),
    onSuccess: (job) => {
      onJob(job.id);
      setPicked(null);
      void refresh();
    },
  });
  const add = (e: FormEvent) => {
    e.preventDefault();
    act.mutate(() => api(`/apps/${appId}/vpn/clients`, { method: "POST", body: { name } }));
    setName("");
  };
  const reached = picked ?? data?.zones ?? [];

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-5" /> {t("vpn.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
        {data && !data.running && <p className="text-sm text-muted-foreground">{t("vpn.stopped")}</p>}
        {data && (
          <p className="text-sm text-muted-foreground">
            {t("vpn.addressing", { subnet: data.subnet, gateway: data.server_address })}
          </p>
        )}
        {data && (
          <>
            <form onSubmit={add} className="flex flex-wrap gap-2">
              <Input aria-label={t("vpn.clientName")} className="w-56" placeholder={t("vpn.clientName")} value={name} maxLength={32} pattern="[A-Za-z0-9 _.\-]+" required onChange={(e) => setName(e.target.value)} />
              <Button type="submit" disabled={act.isPending}>
                <Plus /> {t("vpn.addClient")}
              </Button>
            </form>
            {data.clients.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("vpn.noClient")}</p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {data.clients.map((c) => (
                  <li key={c.id} className="grid gap-3 p-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <Switch
                        aria-label={t("vpn.enabled", { name: c.name })}
                        checked={c.active}
                        onChange={(e) => {
                          const enabled = e.target.checked; // read now: React restores the controlled input before the mutation runs
                          act.mutate(() => api(`/apps/${appId}/vpn/clients/${c.id}`, { method: "PUT", body: { enabled } }));
                        }}
                      />
                      <span
                        className={`size-2.5 rounded-full ${c.online ? "bg-ok" : "bg-idle"}`}
                        role="img"
                        aria-label={c.online ? t("vpn.online") : t("vpn.offline")}
                        title={c.online ? t("vpn.online") : t("vpn.offline")}
                      />
                      <span className="font-medium">{c.name}</span>
                      <span className="font-mono text-xs text-muted-foreground">{c.address}</span>
                      <span className="text-xs text-muted-foreground">
                        {c.online ? t("vpn.online") : c.latest_handshake ? t("vpn.seen", { when: new Date(c.latest_handshake).toLocaleString(lang) }) : t("vpn.never")}
                        {c.endpoint && ` · ${t("vpn.from", { ip: c.endpoint.replace(/:\d+$/, "") })}`}
                        {" · "}↓ {u.size(c.rx)} ↑ {u.size(c.tx)}
                      </span>
                      {c.expires_at && (
                        <span className={`rounded-full px-2 py-0.5 text-xs ${c.active ? "bg-muted" : "bg-danger/15 text-danger"}`}>
                          {c.active ? t("vpn.until", { when: new Date(c.expires_at).toLocaleString(lang) }) : t("vpn.expired")}
                        </span>
                      )}
                      <span className="ml-auto flex gap-1">
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button size="sm" variant="ghost" aria-label={t("vpn.qr", { name: c.name })} title={t("vpn.qr", { name: c.name })}>
                              <QrCode />
                            </Button>
                          </DialogTrigger>
                          <DialogContent title={t("vpn.qr", { name: c.name })} description={t("vpn.qrHelp")} closeLabel={t("common.close")}>
                            {/* An <img> never runs the SVG's scripts; the API also sends CSP sandbox. */}
                            <img src={`/api/v1/apps/${appId}/vpn/clients/${c.id}/qrcode`} alt="" className="mx-auto size-64 rounded-md bg-white p-2" />
                          </DialogContent>
                        </Dialog>
                        <Button size="sm" variant="ghost" asChild>
                          <a href={`/api/v1/apps/${appId}/vpn/clients/${c.id}/config`} download aria-label={t("vpn.config", { name: c.name })} title={t("vpn.config", { name: c.name })}>
                            <Download />
                          </a>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t("vpn.renew", { name: c.name })}
                          title={t("vpn.renew", { name: c.name })}
                          onClick={() => window.confirm(t("vpn.renewConfirm", { name: c.name })) && act.mutate(() => api(`/apps/${appId}/vpn/clients/${c.id}/renew`, { method: "POST" }))}
                        >
                          <KeyRound />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t("vpn.delete", { name: c.name })}
                          title={t("vpn.delete", { name: c.name })}
                          onClick={() => window.confirm(t("vpn.deleteConfirm", { name: c.name })) && act.mutate(() => api(`/apps/${appId}/vpn/clients/${c.id}`, { method: "DELETE" }))}
                        >
                          <Trash2 className="text-danger" />
                        </Button>
                      </span>
                    </div>
                    <ClientSettings key={JSON.stringify([c.name, c.address, c.access, c.routing, c.allowed_ips, c.expires_at])} appId={appId} client={c} vpn={data} zones={zones ?? []} onSaved={refresh} />
                    {c.public_key && <p className="truncate font-mono text-xs text-muted-foreground">{t("vpn.publicKey")} {c.public_key}</p>}
                  </li>
                ))}
              </ul>
            )}
            {act.error && <Alert tone="danger">{errorMessage(act.error)}</Alert>}
          </>
        )}
        {data && (
          <fieldset className="grid gap-2">
            <legend className="mb-1 font-medium">{t("vpn.zones")}</legend>
            <p className="text-sm text-muted-foreground">{t("vpn.zonesHelp")}</p>
            <div className="flex flex-wrap gap-3">
              {zones?.map((z) => {
                const linked = z.network_mode === "shared";
                return (
                  <label key={z.slug} className="flex items-center gap-2 text-sm" title={linked ? undefined : t("vpn.zoneNotLinked")}>
                    <Switch
                      disabled={!linked}
                      checked={reached.includes(z.slug)}
                      onChange={(e) => setPicked(e.target.checked ? [...reached, z.slug] : reached.filter((s) => s !== z.slug))}
                    />
                    <span className="size-2.5 rounded-full" style={{ background: z.color }} /> {z.name}
                  </label>
                );
              })}
            </div>
            {picked && (
              <Button className="justify-self-start" disabled={saveZones.isPending} onClick={() => window.confirm(t("vpn.zonesConfirm")) && saveZones.mutate(picked)}>
                {t("common.save")}
              </Button>
            )}
            {saveZones.error && <Alert tone="danger">{errorMessage(saveZones.error)}</Alert>}
          </fieldset>
        )}
      </CardContent>
    </Card>
  );
}
