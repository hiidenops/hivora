"use client";

import { useState, type FormEvent, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import type { Zone } from "@/lib/api/client";
import { useSaveZone } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const ZONE_COLORS = ["#d97706", "#65a30d", "#0891b2", "#4f46e5", "#c026d3", "#e11d48", "#78716c"];
const MODES = ["none", "shared"] as const;

/** Create a zone, or edit one (name, colour, network). */
export function ZoneDialog({ zone, trigger }: { zone?: Zone; trigger: ReactNode }) {
  const { t, errorMessage } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(zone?.name ?? "");
  const [color, setColor] = useState(zone?.color ?? ZONE_COLORS[0]);
  const [mode, setMode] = useState<string>(zone?.network_mode ?? "none");
  const save = useSaveZone(zone?.slug);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({ name, color, network_mode: mode }, { onSuccess: () => setOpen(false) });
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
            {MODES.map((m) => (
              <label key={m} className={cn("surface grid cursor-pointer gap-0.5 rounded-lg border p-3 text-sm", mode === m && "border-primary")}>
                <span className="flex items-center gap-2 font-medium">
                  <input type="radio" name="network" value={m} checked={mode === m} onChange={() => setMode(m)} />
                  {t(`zones.mode.${m}` as MessageKey)}
                </span>
                <span className="pl-6 text-muted-foreground">{t(`zones.mode.${m}.help` as MessageKey)}</span>
              </label>
            ))}
            {zone && mode !== zone.network_mode && apps > 0 && <Alert tone="warn">{t("zones.redeploy", { n: apps })}</Alert>}
          </fieldset>
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          <Button type="submit" className="justify-self-end" disabled={save.isPending || !name.trim()}>
            {t(zone ? "common.save" : "zones.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
