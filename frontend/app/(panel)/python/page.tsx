"use client";

import { FileArchive, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label, Switch } from "@/components/ui/input";
import { api, upload } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Analysis = components["schemas"]["AnalysisOut"];
type Mount = components["schemas"]["MountIO"];
type Env = components["schemas"]["EnvIO"];
type Port = components["schemas"]["PortIO"];

const section = "surface grid gap-4 rounded-xl border p-5";
const PYTHONS = ["3.13", "3.12", "3.11"];

/** A Python project sent as a .zip: Hivora reads it, you check, it runs. */
export default function PythonProjectPage() {
  const { t, errorMessage } = useI18n();
  const { data: zones } = useZones();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [a, setA] = useState<Analysis | null>(null);
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  const [python, setPython] = useState("3.13");
  const [entry, setEntry] = useState("");
  const [workdir, setWorkdir] = useState("");
  const [requirements, setRequirements] = useState("");
  const [mounts, setMounts] = useState<Mount[]>([]);
  const [env, setEnv] = useState<Env[]>([]);
  const [ports, setPorts] = useState<Port[]>([]);
  const [apt, setApt] = useState("");
  const [done, setDone] = useState<{ app: number; job: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const analyze = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const found = await upload<Analysis>("/apps/python/analyze", file, { query: { filename: file.name }, onProgress: setProgress });
      setA(found);
      setName(found.name);
      setPython(found.python);
      setEntry(found.entry.join(" "));
      setWorkdir(found.workdir);
      setRequirements(found.requirements ?? "");
      setMounts(found.mounts);
      setEnv(found.env);
      setPorts(found.ports.map((p) => ({ container: p, host: p })));
      setApt(found.apt.join(" "));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  const deploy = async () => {
    if (!a) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ app: { id: number }; job: { id: number } }>("/apps/python", {
        method: "POST",
        body: {
          token: a.token, name, zone: zone || null, python, workdir, mounts, env, ports,
          entry: entry.match(/"[^"]*"|\S+/g)?.map((w) => w.replace(/^"|"$/g, "")) ?? [],
          requirements: requirements || null,
          apt: apt.split(/\s+/).filter(Boolean),
        },
      });
      setDone({ app: r.app.id, job: r.job.id });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const edit = <T,>(list: T[], set: (v: T[]) => void, i: number, patch: Partial<T>) => set(list.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  if (done) {
    return (
      <>
        <PageHeader title={t("py.title")} />
        <div className={section}>
          <JobProgress jobId={done.job} />
          <p className="text-sm text-muted-foreground">{t("py.firstStart")}</p>
          <Button asChild className="justify-self-start">
            <Link href={`/app/?id=${done.app}`}>{t("deploy.goToApp")}</Link>
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("py.title")} />
      <div className="grid max-w-4xl gap-4">
        <div className={section}>
          <p className="text-sm text-muted-foreground">{t("py.help")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Input type="file" accept=".zip,application/zip" aria-label={t("py.zip")} className="max-w-md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <Button disabled={!file || busy} onClick={() => void analyze()}>
              <FileArchive /> {progress !== null ? t("worlds.uploading", { percent: Math.round(progress * 100) }) : t("py.analyze")}
            </Button>
          </div>
        </div>
        {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}

        {a && (
          <>
            <div className={section}>
              <h2 className="font-semibold">{t("py.found")}</h2>
              <p className="text-xs text-muted-foreground">{t("py.sources", { files: a.files, notes: a.notes.join(" · ") || "—" })}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="grid gap-1">
                  <Label htmlFor="py-name">{t("py.name")}</Label>
                  <Input id="py-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="py-zone">{t("adopt.zone")}</Label>
                  <select id="py-zone" className="h-10 rounded-md border bg-card px-2 text-sm" value={zone} onChange={(e) => setZone(e.target.value)}>
                    <option value="">{t("adopt.noZone")}</option>
                    {zones?.map((z) => (
                      <option key={z.slug} value={z.slug}>
                        {z.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="py-version">{t("py.python")}</Label>
                  <select id="py-version" className="h-10 rounded-md border bg-card px-2 text-sm" value={python} onChange={(e) => setPython(e.target.value)}>
                    {PYTHONS.map((v) => (
                      <option key={v} value={v}>
                        Python {v}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="py-req">{t("py.requirements")}</Label>
                  <Input id="py-req" className="font-mono text-xs" placeholder="—" value={requirements} onChange={(e) => setRequirements(e.target.value)} />
                </div>
                <div className="grid gap-1 sm:col-span-2">
                  <Label htmlFor="py-entry">{t("py.entry")}</Label>
                  <div className="flex gap-2">
                    <Input id="py-workdir" aria-label={t("py.workdir")} title={t("py.workdir")} className="w-40 font-mono text-xs" value={workdir} onChange={(e) => setWorkdir(e.target.value)} />
                    <Input id="py-entry" className="flex-1 font-mono text-xs" value={entry} onChange={(e) => setEntry(e.target.value)} />
                  </div>
                </div>
              </div>
            </div>

            <div className={section}>
              <h2 className="font-semibold">{t("py.env")}</h2>
              {env.length === 0 && <p className="text-sm text-muted-foreground">{t("py.noEnv")}</p>}
              {env.map((v, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2">
                  <Input aria-label={t("overrides.envKey")} className="w-56 font-mono text-xs" value={v.key} onChange={(e) => edit(env, setEnv, i, { key: e.target.value })} />
                  <Input aria-label={t("overrides.envValue")} type={v.secret ? "password" : "text"} className="min-w-48 flex-1 font-mono text-xs" value={v.value} placeholder={v.secret ? t("py.secretPlaceholder") : ""} onChange={(e) => edit(env, setEnv, i, { value: e.target.value })} />
                  <label className="flex items-center gap-1 text-xs">
                    <Switch checked={!!v.secret} onChange={(e) => edit(env, setEnv, i, { secret: e.target.checked })} /> {t("py.secret")}
                  </label>
                  {v.source && <span className="text-xs text-muted-foreground">{v.source}</span>}
                  <Button size="sm" variant="ghost" aria-label={t("overrides.remove")} onClick={() => setEnv(env.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button size="sm" variant="outline" className="justify-self-start" onClick={() => setEnv([...env, { key: "", value: "", secret: false, source: "" }])}>
                <Plus /> {t("overrides.addEnv")}
              </Button>
            </div>

            <div className={section}>
              <h2 className="font-semibold">{t("py.folders")}</h2>
              {mounts.map((m, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <code className="w-32 truncate font-mono text-xs">{m.source || t("py.wholeProject")}</code>→
                  <Input aria-label={t("overrides.target")} className="w-56 font-mono text-xs" value={m.target} onChange={(e) => edit(mounts, setMounts, i, { target: e.target.value })} />
                  <span className="text-xs text-muted-foreground">{m.data ? t("py.dataFolder") : t("py.codeFolder")}</span>
                </div>
              ))}
              <h3 className="mt-2 text-sm font-medium">{t("overrides.ports")}</h3>
              {ports.map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <Input type="number" aria-label={t("overrides.container")} className="h-9 w-28" value={p.container} onChange={(e) => edit(ports, setPorts, i, { container: Number(e.target.value) })} />→
                  <Input type="number" aria-label={t("overrides.host")} className="h-9 w-28" value={p.host} onChange={(e) => edit(ports, setPorts, i, { host: Number(e.target.value) })} />
                  <Button size="sm" variant="ghost" aria-label={t("overrides.remove")} onClick={() => setPorts(ports.filter((_, j) => j !== i))}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button size="sm" variant="outline" className="justify-self-start" onClick={() => setPorts([...ports, { container: 8000, host: 8000 }])}>
                <Plus /> {t("overrides.addPort")}
              </Button>
              <div className="grid gap-1">
                <Label htmlFor="py-apt">{t("py.apt")}</Label>
                <Input id="py-apt" className="font-mono text-xs" placeholder="ffmpeg libpq5" value={apt} onChange={(e) => setApt(e.target.value)} />
              </div>
            </div>

            <Button className="justify-self-start" disabled={busy || !name || !entry} onClick={() => void deploy()}>
              {t("py.deploy")}
            </Button>
          </>
        )}
      </div>
    </>
  );
}
