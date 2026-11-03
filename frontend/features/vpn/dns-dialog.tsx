"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type Dns = components["schemas"]["DnsOut"];

/** The VPN's own DNS: names (minecraft.local) for an app of its zones or an IP. */
export function DnsDialog({ appId, vpnName }: { appId: number; vpnName: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Globe /> {t("dns.open")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("dns.title", { vpn: vpnName })} description={t("dns.help")} closeLabel={t("common.close")}>
        {open && <DnsRecords appId={appId} />}
      </DialogContent>
    </Dialog>
  );
}

function DnsRecords({ appId }: { appId: number }) {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const key = ["vpn-dns", appId];
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Dns>(`/apps/${appId}/vpn/dns`) });
  const [name, setName] = useState("");
  const [target, setTarget] = useState(""); // an app id, or "ip"
  const [ip, setIp] = useState("");
  const done = () => qc.invalidateQueries({ queryKey: key });
  const add = useMutation({
    mutationFn: () => api(`/apps/${appId}/vpn/dns`, { method: "POST", body: target === "ip" ? { name, ip } : { name, app_id: Number(target) } }),
    onSuccess: () => {
      setName("");
      setIp("");
      void done();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api(`/apps/${appId}/vpn/dns/${id}`, { method: "DELETE" }), onSuccess: done });
  if (error) return <Alert tone="danger">{errorMessage(error)}</Alert>;
  if (!data) return null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <div className="grid gap-4 text-sm">
      {data.enabled ? (
        <p className="text-xs text-muted-foreground">{t("dns.server", { ip: data.server })}</p>
      ) : (
        <Alert tone="warn">{t("dns.disabled")}</Alert>
      )}
      <ul className="grid gap-1">
        {data.records.length === 0 && <li className="text-muted-foreground">{t("dns.empty")}</li>}
        {data.records.map((r) => (
          <li key={r.id} className="flex items-center gap-2 rounded-md border px-2 py-1">
            <span className="font-mono text-xs">{r.name}</span>
            <span className="text-muted-foreground">→</span>
            <span className={r.ip ? "font-mono text-xs" : ""}>{r.ip ?? r.app_name ?? t("dns.gone")}</span>
            <Button size="sm" variant="ghost" className="ml-auto h-7 px-2" aria-label={t("dns.delete", { name: r.name })} loading={remove.isPending && remove.variables === r.id} onClick={() => remove.mutate(r.id)}>
              <Trash2 className="text-danger" />
            </Button>
          </li>
        ))}
      </ul>
      <form className="grid gap-2" onSubmit={submit}>
        <div className="flex flex-wrap gap-2">
          <Input className="h-9 w-44 font-mono text-xs" aria-label={t("dns.name")} placeholder="minecraft.local" value={name} maxLength={253} required onChange={(e) => setName(e.target.value)} />
          <Select className="h-9 w-44" aria-label={t("dns.target")} value={target} required onChange={(e) => setTarget(e.target.value)}>
            <option value="" disabled>
              {t("dns.target")}
            </option>
            {data.targets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
            <option value="ip">{t("dns.ip")}</option>
          </Select>
          {target === "ip" && <Input className="h-9 w-36 font-mono text-xs" aria-label={t("dns.ip")} placeholder="192.168.1.20" value={ip} maxLength={45} required onChange={(e) => setIp(e.target.value)} />}
          <Button type="submit" size="sm" className="h-9" loading={add.isPending} disabled={add.isPending}>
            {t("dns.add")}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{t("dns.local")}</p>
        {add.error && <Alert tone="danger">{errorMessage(add.error)}</Alert>}
      </form>
    </div>
  );
}
