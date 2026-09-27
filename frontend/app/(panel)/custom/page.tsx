"use client";

import { Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Switch } from "@/components/ui/input";
import { api, type Plan } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Image = components["schemas"]["ImageOut"];
type Port = components["schemas"]["CustomPortIn"];
type Env = components["schemas"]["CustomEnvIn"];

const section = "surface grid gap-4 rounded-xl border p-5";

/** Any registry image, as an app Hivora manages like the others. */
export default function CustomImagePage() {
  const { t, errorMessage } = useI18n();
  const { data: zones } = useZones();
  const [ref, setRef] = useState("");
  const [image, setImage] = useState<Image | null>(null);
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  const [ports, setPorts] = useState<Port[]>([]);
  const [volumes, setVolumes] = useState<string[]>([]);
  const [env, setEnv] = useState<Env[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [done, setDone] = useState<{ app: number; job: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = async (f: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await f();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const inspect = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const found = await api<Image>("/apps/images/inspect", { query: { ref } });
      setImage(found);
      setName(found.name.split("/").pop() ?? found.name);
      setPorts(found.ports.map((p, i) => ({ ...p, web: i === 0 && p.protocol === "tcp" })));
      setVolumes(found.volumes);
      setEnv(found.env);
      setPlan(null);
    });
  };
  const body = () => ({ name, image: ref, zone: zone || null, ports, volumes, env });
  const review = () => void run(async () => setPlan(await api<Plan>("/apps/custom/plan", { method: "POST", body: body() })));
  const deploy = () =>
    void run(async () => {
      const r = await api<{ app: { id: number }; job: { id: number } }>("/apps/custom", { method: "POST", body: body() });
      setDone({ app: r.app.id, job: r.job.id });
    });
  const edit = <T,>(list: T[], set: (v: T[]) => void, i: number, patch: Partial<T>) =>
    set(list.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  if (done) {
    return (
      <>
        <PageHeader title={t("custom.title")} />
        <div className={section}>
          <JobProgress jobId={done.job} />
          <Button asChild className="justify-self-start">
            <Link href={`/app/?id=${done.app}`}>{t("deploy.goToApp")}</Link>
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("custom.title")} />
      <div className="grid max-w-4xl gap-4">
        <form className={section} onSubmit={inspect}>
          <Label htmlFor="image-ref">{t("custom.image")}</Label>
          <div className="flex gap-2">
            <Input id="image-ref" className="font-mono" placeholder="grafana/grafana:12.2.0" value={ref} maxLength={300} required onChange={(e) => setRef(e.target.value)} />
            <Button type="submit" disabled={busy || !ref.trim()}>
              <Search /> {t("custom.read")}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t("custom.imageHelp")}</p>
          {image && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono">
                {image.name}:{image.tag}
              </span>
              <span className="font-mono text-xs text-muted-foreground">{image.digest.slice(0, 19)}</span>
              {image.platforms.map((p) => (
                <Badge key={p}>{p}</Badge>
              ))}
              {!image.compatible && <Alert tone="danger">{t("custom.incompatible")}</Alert>}
            </div>
          )}
        </form>

        {image?.compatible && (
          <>
            <section className={section}>
              <h2 className="font-semibold">{t("custom.general")}</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="app-name">{t("deploy.name")}</Label>
                  <Input id="app-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="app-zone">{t("deploy.zone")}</Label>
                  <Select id="app-zone" value={zone} onChange={(e) => setZone(e.target.value)}>
                    <option value="">{t("dashboard.unclassified")}</option>
                    {zones?.map((z) => (
                      <option key={z.slug} value={z.slug}>{z.name}</option>
                    ))}
                  </Select>
                </div>
              </div>
            </section>

            <section className={section}>
              <h2 className="font-semibold">{t("custom.ports")}</h2>
              {ports.map((p, i) => (
                <div key={i} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[1fr_1fr_6rem_9rem_auto_auto]">
                  <Input aria-label={t("custom.containerPort")} type="number" min={1} max={65535} value={p.container} onChange={(e) => edit(ports, setPorts, i, { container: Number(e.target.value) })} />
                  <Input aria-label={t("custom.hostPort")} type="number" min={1} max={65535} value={p.host} onChange={(e) => edit(ports, setPorts, i, { host: Number(e.target.value) })} />
                  <Select aria-label={t("custom.protocol")} value={p.protocol} onChange={(e) => edit(ports, setPorts, i, { protocol: e.target.value as Port["protocol"] })}>
                    <option value="tcp">TCP</option>
                    <option value="udp">UDP</option>
                  </Select>
                  <Select aria-label={t("custom.exposure")} value={p.exposure} onChange={(e) => edit(ports, setPorts, i, { exposure: e.target.value as Port["exposure"] })}>
                    <option value="lan">{t("custom.exposure.lan")}</option>
                    <option value="public">{t("custom.exposure.public")}</option>
                    <option value="internal">{t("custom.exposure.internal")}</option>
                  </Select>
                  <label className="flex h-9 items-center gap-2 text-sm">
                    <Switch checked={!!p.web} onChange={(e) => edit(ports, setPorts, i, { web: e.target.checked })} /> {t("custom.web")}
                  </label>
                  <Button type="button" variant="ghost" size="icon" aria-label={t("action.remove")} onClick={() => setPorts(ports.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <p className="text-xs text-muted-foreground">{t("custom.portsHelp")}</p>
              <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setPorts([...ports, { container: 80, host: 8090, protocol: "tcp", exposure: "lan", web: false }])}>
                <Plus /> {t("custom.addPort")}
              </Button>
            </section>

            <section className={section}>
              <h2 className="font-semibold">{t("custom.volumes")}</h2>
              {volumes.map((v, i) => (
                <div key={i} className="flex gap-2">
                  <Input aria-label={t("custom.volumePath")} className="font-mono" value={v} onChange={(e) => setVolumes(volumes.map((x, j) => (j === i ? e.target.value : x)))} />
                  <Button type="button" variant="ghost" size="icon" aria-label={t("action.remove")} onClick={() => setVolumes(volumes.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <p className="text-xs text-muted-foreground">{t("custom.volumesHelp")}</p>
              <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setVolumes([...volumes, "/data"])}>
                <Plus /> {t("custom.addVolume")}
              </Button>
            </section>

            <section className={section}>
              <h2 className="font-semibold">{t("custom.env")}</h2>
              {env.map((e, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_auto_auto] items-center gap-2">
                  <Input aria-label={t("custom.envKey")} className="font-mono" value={e.key} onChange={(ev) => edit(env, setEnv, i, { key: ev.target.value })} />
                  <Input aria-label={t("custom.envValue")} type={e.secret ? "password" : "text"} className="font-mono" value={e.value ?? ""} onChange={(ev) => edit(env, setEnv, i, { value: ev.target.value })} />
                  <label className="flex items-center gap-2 text-sm">
                    <Switch checked={!!e.secret} onChange={(ev) => edit(env, setEnv, i, { secret: ev.target.checked })} /> {t("custom.secret")}
                  </label>
                  <Button type="button" variant="ghost" size="icon" aria-label={t("action.remove")} onClick={() => setEnv(env.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setEnv([...env, { key: "", value: "", secret: false }])}>
                <Plus /> {t("custom.addEnv")}
              </Button>
            </section>

            {plan && (
              <section className={section}>
                <h2 className="font-semibold">{t("deploy.previewTitle")}</h2>
                {plan.conflicts.map((c) => (
                  <Alert key={`${c.port}/${c.protocol}`} tone="danger">
                    {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
                  </Alert>
                ))}
                {plan.public_ports.length > 0 && <Alert tone="warn">{t("deploy.public")}</Alert>}
                <CodeView code={plan.compose_yaml} />
              </section>
            )}
            <div className="flex gap-2">
              <Button variant={plan ? "outline" : "default"} disabled={busy || !name.trim()} onClick={review}>
                {t("deploy.preview")}
              </Button>
              {plan && (
                <Button disabled={busy || plan.conflicts.length > 0} onClick={deploy}>
                  {t("action.deploy")}
                </Button>
              )}
            </div>
          </>
        )}
        {error != null && <Alert tone="danger">{errorMessage(error)}</Alert>}
      </div>
    </>
  );
}
