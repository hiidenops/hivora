"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { api, type JobRef, type Zone } from "@/lib/api/client";
import { keys, useApps, useSaveZone } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const ZONE_COLORS = ["#d97706", "#65a30d", "#0891b2", "#4f46e5", "#c026d3", "#e11d48", "#78716c"];
const MODES = ["none", "shared"] as const;
const VPN_CHOICES = ["none", "existing", "new"] as const;
type VpnChoice = (typeof VPN_CHOICES)[number];

/** Create a zone, or edit one (name, colour, network). A new zone may come with its VPN:
 *  an existing one serves it, or a new WireGuard is deployed for it. */
export function ZoneDialog({ zone, trigger }: { zone?: Zone; trigger: ReactNode }) {
  const { t, errorMessage } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(zone?.name ?? "");
  const [color, setColor] = useState(zone?.color ?? ZONE_COLORS[0]);
  const [mode, setMode] = useState<string>(zone?.network_mode ?? "none");
  const save = useSaveZone(zone?.slug);
  const router = useRouter();
  const qc = useQueryClient();
  const { data: allApps } = useApps();
  const vpns = (allApps ?? []).filter((a) => a.template === "wireguard");
  const [vpn, setVpn] = useState<VpnChoice>("none");
  const [vpnId, setVpnId] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<unknown>(null);
  const chosenVpn = vpnId || String(vpns[0]?.id ?? "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setLinkError(null);
    save.mutate(
      { name, color, network_mode: vpn === "none" ? mode : "shared" },
      {
        onSuccess: async (created) => {
          if (vpn === "new") {
            const q = new URLSearchParams({ template: "wireguard", vpn_zone: created.slug, name: `VPN ${created.name}` });
            router.push(`/deploy/?${q}`);
            return;
          }
          if (vpn === "existing" && chosenVpn) {
            setLinking(true);
            try {
              const current = await api<{ zones: string[] }>(`/apps/${chosenVpn}/vpn`);
              await api<JobRef>(`/apps/${chosenVpn}/vpn/zones`, { method: "PUT", body: { zones: [...current.zones, created.slug] } });
              void qc.invalidateQueries({ queryKey: keys.zones });
            } catch (err) {
              setLinkError(err); // the zone exists: it can still be linked from the VPN card
              return;
            } finally {
              setLinking(false);
            }
          }
          setOpen(false);
        },
      },
    );
  };
  const apps = zone?.apps ?? 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent title={t(zone ? "zones.edit" : "zones.create")} closeLabel={t("common.close")}>
        <form className="grid gap-5" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="zone-name">{t("zones.name")}</Label>
            <Input id="zone-name" value={name} maxLength={100} required onChange={(e) => setName(e.target.value)} />
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm font-medium">{t("zones.color")}</legend>
            <div className="flex flex-wrap items-center gap-2">
              {ZONE_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-label={c}
                  aria-pressed={color === c}
                  onClick={() => setColor(c)}
                  className={cn("size-8 rounded-full ring-offset-2 ring-offset-card transition-transform hover:scale-110", color === c && "ring-2 ring-foreground")}
                  style={{ background: c }}
                />
              ))}
              <input type="color" aria-label={t("zones.customColor")} value={color} onChange={(e) => setColor(e.target.value)} className="size-8 rounded-full" />
            </div>
          </fieldset>
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm font-medium">{t("zones.network")}</legend>
            {!zone && vpn !== "none" && <Alert tone="info">{t("zones.vpn.shared")}</Alert>}
            {zone?.vpn && <Alert tone="info">{t("zones.vpnReached", { vpn: zone.vpn, subnet: zone.subnet ?? "—" })}</Alert>}
            {MODES.map((m) => (
              <label key={m} className={cn("surface grid cursor-pointer gap-0.5 rounded-lg border p-3 text-sm", mode === m && "border-primary", (zone?.vpn || vpn !== "none") && "opacity-60")}>
                <span className="flex items-center gap-2 font-medium">
                  <input type="radio" name="network" value={m} checked={vpn === "none" ? mode === m : m === "shared"} disabled={Boolean(zone?.vpn) || vpn !== "none"} onChange={() => setMode(m)} />
                  {t(`zones.mode.${m}` as MessageKey)}
                </span>
                <span className="pl-6 text-muted-foreground">{t(`zones.mode.${m}.help` as MessageKey)}</span>
              </label>
            ))}
            {zone && mode !== zone.network_mode && apps > 0 && <Alert tone="warn">{t("zones.redeploy", { n: apps })}</Alert>}
          </fieldset>
          {!zone && (
            <fieldset className="grid gap-2">
              <legend className="mb-2 text-sm font-medium">{t("zones.vpn")}</legend>
              {VPN_CHOICES.filter((c) => c !== "existing" || vpns.length > 0).map((c) => (
                <label key={c} className={cn("surface grid cursor-pointer gap-0.5 rounded-lg border p-3 text-sm", vpn === c && "border-primary")}>
                  <span className="flex items-center gap-2 font-medium">
                    <input type="radio" name="vpn" value={c} checked={vpn === c} onChange={() => setVpn(c)} />
                    {t(`zones.vpn.${c}` as MessageKey)}
                  </span>
                  <span className="pl-6 text-muted-foreground">{t(`zones.vpn.${c}.help` as MessageKey)}</span>
                  {c === "existing" && vpn === "existing" && (
                    <Select aria-label={t("zones.vpn.existing")} className="mt-2 ml-6 w-auto" value={chosenVpn} onChange={(e) => setVpnId(e.target.value)}>
                      {vpns.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </Select>
                  )}
                </label>
              ))}
            </fieldset>
          )}
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          {linkError != null && <Alert tone="danger">{t("zones.vpn.linkFailed", { error: errorMessage(linkError) })}</Alert>}
          <Button type="submit" className="justify-self-end" loading={save.isPending || linking} disabled={save.isPending || linking || !name.trim()}>
            {t(zone ? "common.save" : vpn === "new" ? "zones.vpn.createAndDeploy" : "zones.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
