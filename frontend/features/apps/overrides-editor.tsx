"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/input";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

export type Overrides = components["schemas"]["Overrides"];
type Service = components["schemas"]["ServiceOverrides"];
type Port = components["schemas"]["ExtraPort"];
type Volume = components["schemas"]["ExtraVolume"];

const select = "h-9 rounded-md border bg-card px-2 text-sm";

/** Advanced settings of each service: variables, extra ports and folders, limits, restart. */
export function OverridesEditor({ services, value, onChange }: { services: string[]; value: Overrides; onChange: (v: Overrides) => void }) {
  const { t } = useI18n();
  const of = (name: string): Service => value.services?.[name] ?? {};
  const set = (name: string, patch: Partial<Service>) => onChange({ services: { ...value.services, [name]: { ...of(name), ...patch } } });

  return (
    <div className="grid gap-5">
      <p className="text-sm text-muted-foreground">{t("overrides.help")}</p>
      {services.map((name) => {
        const s = of(name);
        const env = Object.entries(s.env ?? {});
        const ports = s.ports ?? [];
        const volumes = s.volumes ?? [];
        const setEnv = (rows: [string, string][]) => set(name, { env: Object.fromEntries(rows) });
        const setPort = (i: number, patch: Partial<Port>) => set(name, { ports: ports.map((p, j) => (i === j ? { ...p, ...patch } : p)) });
        const setVol = (i: number, patch: Partial<Volume>) => set(name, { volumes: volumes.map((v, j) => (i === j ? { ...v, ...patch } : v)) });
        return (
          <fieldset key={name} className="grid gap-4 rounded-lg border p-4">
            {services.length > 1 && <legend className="px-1 font-mono text-sm font-medium">{name}</legend>}

            <div className="grid gap-2">
              <h4 className="text-sm font-medium">{t("overrides.env")}</h4>
              {env.map(([k, v], i) => (
                <div key={i} className="flex gap-2">
                  <Input aria-label={t("overrides.envKey")} placeholder="NOM" className="h-9 w-48 font-mono text-xs" value={k} onChange={(e) => setEnv(env.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
                  <Input aria-label={t("overrides.envValue")} className="h-9 flex-1 font-mono text-xs" value={v} onChange={(e) => setEnv(env.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
                  <Button type="button" size="sm" variant="ghost" aria-label={t("overrides.remove")} onClick={() => setEnv(env.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => setEnv([...env, ["", ""]])}>
                <Plus /> {t("overrides.addEnv")}
              </Button>
            </div>

            <div className="grid gap-2">
              <h4 className="text-sm font-medium">{t("overrides.ports")}</h4>
              {ports.map((p, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <Input type="number" min={1} max={65535} aria-label={t("overrides.container")} placeholder={t("overrides.container")} className="h-9 w-28" value={p.container || ""} onChange={(e) => setPort(i, { container: Number(e.target.value) })} />
                  →
                  <Input type="number" min={1} max={65535} aria-label={t("overrides.host")} placeholder={t("overrides.host")} className="h-9 w-28" value={p.host || ""} onChange={(e) => setPort(i, { host: Number(e.target.value) })} />
                  <select aria-label={t("overrides.protocol")} className={select} value={p.protocol ?? "tcp"} onChange={(e) => setPort(i, { protocol: e.target.value as Port["protocol"] })}>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                  </select>
                  <select aria-label={t("overrides.exposure")} className={select} value={p.exposure ?? "lan"} onChange={(e) => setPort(i, { exposure: e.target.value as Port["exposure"] })}>
                    <option value="lan">{t("custom.exposure.lan")}</option>
                    <option value="public">{t("custom.exposure.public")}</option>
                  </select>
                  <Button type="button" size="sm" variant="ghost" aria-label={t("overrides.remove")} onClick={() => set(name, { ports: ports.filter((_, j) => j !== i) })}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => set(name, { ports: [...ports, { container: 0, host: 0, protocol: "tcp", exposure: "lan" }] })}>
                <Plus /> {t("overrides.addPort")}
              </Button>
            </div>

            <div className="grid gap-2">
              <h4 className="text-sm font-medium">{t("overrides.volumes")}</h4>
              {volumes.map((v, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <Input aria-label={t("overrides.folder")} placeholder={t("overrides.folder")} className="h-9 w-40 font-mono text-xs" value={v.name} onChange={(e) => setVol(i, { name: e.target.value })} />
                  →
                  <Input aria-label={t("overrides.target")} placeholder="/chemin/dans/le/conteneur" className="h-9 w-64 font-mono text-xs" value={v.target} onChange={(e) => setVol(i, { target: e.target.value })} />
                  <label className="flex items-center gap-2">
                    <Switch checked={!!v.read_only} onChange={(e) => setVol(i, { read_only: e.target.checked })} /> {t("overrides.readOnly")}
                  </label>
                  <Button type="button" size="sm" variant="ghost" aria-label={t("overrides.remove")} onClick={() => set(name, { volumes: volumes.filter((_, j) => j !== i) })}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => set(name, { volumes: [...volumes, { name: "", target: "", read_only: false }] })}>
                <Plus /> {t("overrides.addVolume")}
              </Button>
            </div>

            <div className="flex flex-wrap items-end gap-3 text-sm">
              <label className="grid gap-1">
                {t("overrides.cpus")}
                <Input type="number" min={0.1} step={0.1} className="h-9 w-28" placeholder="∞" value={s.cpus ?? ""} onChange={(e) => set(name, { cpus: e.target.value ? Number(e.target.value) : null })} />
              </label>
              <label className="grid gap-1">
                {t("overrides.memory")}
                <Input className="h-9 w-28 font-mono" placeholder="512m, 2g" value={s.memory ?? ""} onChange={(e) => set(name, { memory: e.target.value.trim().toLowerCase() || null })} />
              </label>
              <label className="grid gap-1">
                {t("overrides.restart")}
                <select className={select} value={s.restart ?? ""} onChange={(e) => set(name, { restart: (e.target.value || null) as Service["restart"] })}>
                  <option value="">{t("overrides.restartDefault")}</option>
                  <option value="unless-stopped">unless-stopped</option>
                  <option value="always">always</option>
                  <option value="on-failure">on-failure</option>
                  <option value="no">no</option>
                </select>
              </label>
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
