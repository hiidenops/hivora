"use client";

import { Globe, House, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { GeneratedForm, initialValues, type FieldDef, type Values } from "@/features/deploy/generated-form";
import { ApiError, type Plan } from "@/lib/api/client";
import { useDeploy, usePlan, useTemplate, useZones } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Step = "form" | "review" | "progress";
type Access = "public" | "lan" | "vpn";

function Deploy() {
  const { t, errorMessage } = useI18n();
  const { advanced } = useSession();
  const params = useSearchParams();
  const slug = params.get("template") ?? "";
  const { data: template, error: loadError } = useTemplate(slug);
  const { data: zones } = useZones();
  const planMutation = usePlan();
  const deploy = useDeploy();

  const form = template?.form as { basic?: FieldDef[]; advanced?: FieldDef[] } | undefined;
  const basic = useMemo(() => form?.basic ?? [], [form]);
  const advancedFields = useMemo(() => form?.advanced ?? [], [form]);
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  // Where the app is reached: its ports on the Internet, on the LAN only, or through a VPN
  // (a zone a VPN reaches: nothing published). Null: no port to publish (the zone only).
  const [access, setAccess] = useState<Access | null>(null);
  const [values, setValues] = useState<Values>({});
  const [step, setStep] = useState<Step>("form");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [result, setResult] = useState<{ appId: number; jobId: number } | null>(null);
  const [finished, setFinished] = useState<string | null>(null);

  // The zone the template suggests (e.g. Administration for a VPN), when it exists; a zone a
  // VPN reaches only goes with "through the VPN".
  useEffect(() => {
    if (!template || !zones) return;
    const suggested = zones.find((z) => z.slug === template.default_zone);
    const initial: Access | null = template.default_access ? (suggested?.vpn ? "vpn" : template.default_access) : null;
    setAccess((a) => a ?? initial);
    if (suggested && (!suggested.vpn || initial === "vpn" || !template.default_access)) setZone((z) => z || suggested.slug);
  }, [template, zones]);
  const vpnZones = (zones ?? []).filter((z) => z.vpn);
  const offered = access === null ? (zones ?? []) : (zones ?? []).filter((z) => Boolean(z.vpn) === (access === "vpn"));
  const pick = (a: Access) => {
    setAccess(a);
    const fits = (zones ?? []).find((z) => z.slug === zone && Boolean(z.vpn) === (a === "vpn"));
    if (!fits) setZone(a === "vpn" ? (vpnZones[0]?.slug ?? "") : "");
  };

  useEffect(() => {
    if (!template) return;
    // Links (e.g. the modpack catalog) may prefill non-secret fields and the name.
    const fields = [...basic, ...advancedFields];
    const prefill = Object.fromEntries(
      fields.filter((f) => f.type !== "secret" && params.has(f.id)).map((f) => [f.id, params.get(f.id)]),
    );
    setName(params.get("name") ?? template.name);
    setValues({ ...initialValues(fields), ...prefill });
  }, [template, basic, advancedFields, params]);

  const error = planMutation.error ?? deploy.error;
  const fieldErrors =
    error instanceof ApiError && error.code === "form_invalid"
      ? (error.details.fields as Record<string, string>)
      : {};
  // Only a change from the template's own choice is sent (its other ports stay as they are).
  const chosen = access === "public" || access === "lan" ? access : null;
  const body = () => ({
    template: slug,
    name,
    inputs: values,
    zone: zone || null,
    access: chosen && chosen !== template?.default_access ? chosen : null,
  });
  const setValue = (id: string, value: unknown) => setValues((v) => ({ ...v, [id]: value }));
  const review = () =>
    planMutation.mutate(body(), {
      onSuccess: (p) => {
        setPlan(p);
        setStep("review");
      },
    });

  if (loadError) return <Alert tone="danger">{errorMessage(loadError)}</Alert>;
  if (!template) {
    return (
      <div role="status" aria-label={t("common.loading")} className="grid max-w-2xl gap-4">
        <Skeleton className="h-9 w-1/2" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <AppIcon src={template.icon_url} name={template.name} />
            {t("deploy.title", { name: template.name })}
          </span>
        }
      />
      {step === "form" && (
        <div className="grid gap-4">
          <div className="grid gap-4 rounded-lg border surface p-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="app-name">{t("deploy.name")}</Label>
              <Input id="app-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="app-zone">{t("deploy.zone")}</Label>
              <Select id="app-zone" value={zone} onChange={(e) => setZone(e.target.value)} disabled={access === "vpn" && vpnZones.length === 0}>
                {access !== "vpn" && <option value="">{t("dashboard.unclassified")}</option>}
                {offered.map((z) => (
                  <option key={z.slug} value={z.slug}>
                    {z.vpn ? t("deploy.zoneVpn", { zone: z.name, vpn: z.vpn }) : z.name}
                  </option>
                ))}
              </Select>
            </div>
            {access !== null && (
              <fieldset className="grid gap-2 sm:col-span-2">
                <legend className="mb-1.5 text-sm font-medium">{t("deploy.access")}</legend>
                <div role="radiogroup" className="grid gap-2 sm:grid-cols-3">
                  {(["public", "lan", "vpn"] as const).map((a) => (
                    <button
                      key={a}
                      type="button"
                      role="radio"
                      aria-checked={access === a}
                      onClick={() => pick(a)}
                      className={cn(
                        "grid gap-1 rounded-lg border p-3 text-left transition-colors",
                        access === a ? "border-primary bg-primary/10 ring-2 ring-primary" : "bg-card hover:bg-muted",
                      )}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium">
                        {a === "public" ? <Globe className="size-4" /> : a === "lan" ? <House className="size-4" /> : <ShieldCheck className="size-4" />}
                        {t(`deploy.access.${a}` as MessageKey)}
                      </span>
                      <span className="text-xs text-muted-foreground">{t(`deploy.access.${a}.help` as MessageKey)}</span>
                    </button>
                  ))}
                </div>
                {access === "vpn" && vpnZones.length === 0 && <Alert tone="warn">{t("deploy.access.vpn.none")}</Alert>}
                {access === "vpn" && vpnZones.length > 0 && <p className="text-xs text-muted-foreground">{t("deploy.access.vpn.zone")}</p>}
                {access === "public" && <p className="text-xs text-warn">{t("deploy.access.public.warn")}</p>}
              </fieldset>
            )}
          </div>
          <GeneratedForm fields={basic} values={values} errors={fieldErrors} onChange={setValue} appName={name} />
          {advancedFields.length > 0 && (
            <details open={advanced || advancedFields.some((f) => fieldErrors[f.id])}>
              <summary className="surface rounded-lg border px-4 py-3 text-sm font-medium transition-shadow duration-200 hover:shadow-md">
                {t("deploy.advanced")}
              </summary>
              <div className="mt-4">
                <GeneratedForm
                  fields={advancedFields}
                  values={values}
                  errors={fieldErrors}
                  onChange={setValue}
                  appName={name}
                />
              </div>
            </details>
          )}
          {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          <Button className="justify-self-start" onClick={review} disabled={planMutation.isPending || (access === "vpn" && !zone)}>
            {t("deploy.preview")}
          </Button>
        </div>
      )}

      {step === "review" && plan && (
        <div className="animate-enter grid max-w-4xl gap-4">
          <Card>
            <CardHeader>
              <CardTitle>{t("deploy.previewTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              {plan.conflicts.map((c) => (
                <Alert key={`${c.port}/${c.protocol}`} tone="danger" className="flex flex-wrap items-center gap-3">
                  {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
                  {c.suggestion && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const field = [...basic, ...advancedFields].find(
                          (f) => f.type === "port" && values[f.id] === c.port,
                        );
                        if (field) setValue(field.id, c.suggestion);
                        setStep("form");
                      }}
                    >
                      {t("deploy.useSuggestion", { port: c.suggestion })}
                    </Button>
                  )}
                </Alert>
              ))}
              {plan.public_ports.length > 0 && <Alert tone="warn">{t("deploy.public")}</Alert>}
              <div>
                <h4 className="mb-2 text-sm font-medium">{t("deploy.ports")}</h4>
                <ul className="flex flex-wrap gap-2">
                  {plan.ports
                    .filter((p) => p.host_port)
                    .map((p) => (
                      <li key={`${p.service}-${p.container_port}`} className="rounded-md border px-2 py-1 font-mono text-xs">
                        {p.host_ip ?? "0.0.0.0"}:{p.host_port} → {p.container_port}/{p.protocol}{" "}
                        <span className="text-muted-foreground">({p.exposure})</span>
                      </li>
                    ))}
                </ul>
              </div>
              {plan.volumes.length > 0 && (
                <div>
                  <h4 className="mb-2 text-sm font-medium">{t("deploy.volumes")}</h4>
                  <ul className="grid gap-1 font-mono text-xs">
                    {plan.volumes.map((v) => (
                      <li key={v}>{v}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <h4 className="mb-2 text-sm font-medium">{t("deploy.compose")}</h4>
                <CodeView code={plan.compose_yaml} />
              </div>
              {deploy.error && <Alert tone="danger">{errorMessage(deploy.error)}</Alert>}
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep("form")}>
                  {t("common.back")}
                </Button>
                <Button
                  disabled={plan.conflicts.length > 0 || deploy.isPending}
                  onClick={() =>
                    deploy.mutate(body(), {
                      onSuccess: (r) => {
                        setResult({ appId: r.app.id, jobId: r.job.id });
                        setStep("progress");
                      },
                    })
                  }
                >
                  {t("deploy.submit")}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {step === "progress" && result && (
        <Card className="animate-enter w-full">
          <CardHeader>
            <CardTitle>
              {finished === "succeeded"
                ? t("deploy.done")
                : finished
                  ? t("deploy.failed")
                  : t("deploy.progress")}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <JobProgress jobId={result.jobId} onFinished={setFinished} />
            {finished === "succeeded" && plan && Object.keys(plan.access).length > 0 && (
              <div>
                <h4 className="mb-2 text-sm font-medium">{t("deploy.access")}</h4>
                {Object.entries(plan.access).map(([k, v]) => (
                  <CodeView key={k} code={v} />
                ))}
              </div>
            )}
            {finished && (
              <Button asChild className="justify-self-start">
                <Link href={`/app/?id=${result.appId}`}>{t("deploy.goToApp")}</Link>
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

export default function DeployPage() {
  return (
    <Suspense>
      <Deploy />
    </Suspense>
  );
}
