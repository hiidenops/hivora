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
import { useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Vpn = components["schemas"]["VpnOut"];
type Client = components["schemas"]["VpnClientOut"];

const ips = (text: string) => text.split(/[\s,]+/).filter(Boolean);

function ClientNetwork({ appId, client, defaultIps, onSaved }: { appId: number; client: Client; defaultIps: string; onSaved: () => void }) {
  const { t, errorMessage } = useI18n();
  const [address, setAddress] = useState(client.address ?? "");
  const [text, setText] = useState((client.allowed_ips ?? []).join(", "));
  const save = useMutation({
    mutationFn: () =>
      api(`/apps/${appId}/vpn/clients/${client.id}`, {
        method: "PUT",
        body: { ...(text.trim() ? { allowed_ips: ips(text) } : { clear_allowed_ips: true }), address: address.trim() || null },
      }),
    onSuccess: onSaved,
  });
  return (
    <form
      className="flex flex-wrap gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Input aria-label={t("vpn.address")} title={t("vpn.address")} className="h-8 w-32 font-mono text-xs" value={address} maxLength={15} onChange={(e) => setAddress(e.target.value)} />
      <Input aria-label={t("vpn.allowedIps")} title={t("vpn.allowedIps")} className="h-8 min-w-48 flex-1 font-mono text-xs" placeholder={t("vpn.defaultIps", { ips: defaultIps })} value={text} onChange={(e) => setText(e.target.value)} />
      <Button type="submit" size="sm" variant="outline" disabled={save.isPending}>
        {t("common.save")}
      </Button>
      {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    </form>
  );
}

/** Clients of the WireGuard server and the zones it reaches: Hivora writes its config. */
export function VpnCard({ appId, onJob }: { appId: number; onJob: (id: number) => void }) {
  const { t, lang, errorMessage } = useI18n();
  const qc = useQueryClient();
  const key = ["apps", appId, "vpn"];
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
                        checked={c.enabled}
                        onChange={(e) => {
                          const enabled = e.target.checked; // read now: React restores the controlled input before the mutation runs
                          act.mutate(() => api(`/apps/${appId}/vpn/clients/${c.id}`, { method: "PUT", body: { enabled } }));
                        }}
                      />
                      <span className="font-medium">{c.name}</span>
                      <span className="font-mono text-xs text-muted-foreground">{c.address}</span>
                      <span className="text-xs text-muted-foreground">
                        {c.latest_handshake ? t("vpn.seen", { when: new Date(c.latest_handshake).toLocaleString(lang) }) : t("vpn.never")}
                        {" · "}↓ {u.size(c.rx)} ↑ {u.size(c.tx)}
                      </span>
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
                    <ClientNetwork key={`${c.address}|${(c.allowed_ips ?? []).join()}`} appId={appId} client={c} defaultIps={data.default_allowed_ips} onSaved={refresh} />
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
