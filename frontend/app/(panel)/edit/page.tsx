"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { DiffView } from "@/components/diff-view";
import { OverridesEditor, type Overrides } from "@/features/apps/overrides-editor";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { units } from "@/features/activity/host-charts";
import { GeneratedForm, type FieldDef, type Values } from "@/features/deploy/generated-form";
import { ApiError, type UpdatePlan } from "@/lib/api/client";
import { useApp, useAppSettings, usePlanUpdate, useUpdateSettings } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

type Step = "form" | "review" | "progress";

/** Changed lines other than the revision bookkeeping (header comment, label). */
function hasChanges(diff: string): boolean {
  return diff
    .split("\n")
    .some((l) => /^[+-](?![+-]{2})/.test(l) && !/revision/.test(l));
}

function Edit() {
  const { t, l, lang, errorMessage } = useI18n();
  const { advanced } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: app } = useApp(id);
  const { data: settings, error: loadError } = useAppSettings(id);
  const plan = usePlanUpdate(id);
  const apply = useUpdateSettings(id);
  const [values, setValues] = useState<Values>({});
  const [step, setStep] = useState<Step>("form");
  const [review, setReview] = useState<UpdatePlan | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [overrides, setOverrides] = useState<Overrides>({ services: {} });

  const form = settings?.form as { basic?: FieldDef[]; advanced?: FieldDef[] } | undefined;
  const basic = useMemo(() => form?.basic ?? [], [form]);
  const advancedFields = useMemo(() => form?.advanced ?? [], [form]);
  useEffect(() => {
    if (settings) {
      setValues(settings.values);
      setOverrides(settings.overrides);
    }
  }, [settings]);
  // Empty rows are left out (an added line never filled in).
  const cleaned = (): Overrides => ({
    services: Object.fromEntries(
      Object.entries(overrides.services ?? {}).map(([name, s]) => [
        name,
        {
          ...s,
          env: Object.fromEntries(Object.entries(s.env ?? {}).filter(([k]) => k.trim())),
          ports: (s.ports ?? []).filter((p) => p.container && p.host),
          volumes: (s.volumes ?? []).filter((v) => v.name && v.target),
        },
      ]),
    ),
  });
  const hasOverrides = Object.values(settings?.overrides.services ?? {}).some((s) => Object.keys(s).length > 0);

  const error = plan.error ?? apply.error;
  const fieldErrors =
    error instanceof ApiError && error.code === "form_invalid" ? (error.details.fields as Record<string, string>) : {};
  const setValue = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }));

  if (loadError) return <Alert tone="danger">{errorMessage(loadError)}</Alert>;
  if (!settings || !app) {
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
            <AppIcon src={app.icon_url} name={app.name} />
            {t("edit.title", { name: app.name })}
          </span>
        }
      />
      {step === "form" && (
        <div className="grid gap-4">
          <GeneratedForm
            fields={basic}
            values={values}
            errors={fieldErrors}
            onChange={setValue}
            appName={app.name}
            secretsSet={settings.secrets_set}
          />
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
                  appName={app.name}
                  secretsSet={settings.secrets_set}
                />
              </div>
            </details>
          )}
          {(advanced || hasOverrides) && (
            <details open={hasOverrides}>
              <summary className="surface rounded-lg border px-4 py-3 text-sm font-medium transition-shadow duration-200 hover:shadow-md">
                {t("overrides.title")}
              </summary>
              <div className="mt-4">
                <OverridesEditor services={settings.services} value={overrides} onChange={setOverrides} />
              </div>
            </details>
          )}
          {settings.custom_compose && <Alert tone="warn">{t("overrides.customCompose")}</Alert>}
          {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
          <div className="flex gap-2">
            <Button variant="outline" asChild>
              <Link href={`/app/?id=${id}`}>{t("common.cancel")}</Link>
            </Button>
            <Button
              disabled={plan.isPending}
              onClick={() =>
                plan.mutate({ inputs: values, overrides: cleaned() }, {
                  onSuccess: (p) => {
                    setReview(p);
                    setConfirmReset(false);
                    setStep("review");
                  },
                })
              }
            >
              {t("edit.review")}
            </Button>
          </div>
        </div>
      )}

      {step === "review" && review && (
        <Card className="animate-enter max-w-4xl">
          <CardHeader>
            <CardTitle>{t("deploy.previewTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {review.conflicts.map((c) => (
              <Alert key={`${c.port}/${c.protocol}`} tone="danger">
                {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
              </Alert>
            ))}
            {review.public_ports.length > 0 && <Alert tone="warn">{t("deploy.public")}</Alert>}
            {review.replaces_custom && <Alert tone="warn">{t("overrides.replacesCustom")}</Alert>}
            {review.reset && (
              <Alert tone="danger" className="grid gap-3">
                <p className="font-medium">
                  {t("edit.resetWarning", {
                    fields: review.reset.fields
                      .map((f) => l([...basic, ...advancedFields].find((d) => d.id === f)?.label ?? f))
                      .join(", "),
                    size: units(lang).size(review.reset.size),
                  })}
                </p>
                <p>
                  {t("edit.resetKept")}{" "}
                  <Link href={`/app/?id=${id}`} className="underline">
                    {t("edit.resetBackup")}
                  </Link>
                </p>
                <label className="flex items-center gap-3 font-medium">
                  <Switch checked={confirmReset} onChange={(e) => setConfirmReset(e.target.checked)} />
                  {t("edit.resetConfirm")}
                </label>
              </Alert>
            )}
            <div>
              <h4 className="mb-2 text-sm font-medium">
                {t("edit.diff", { from: review.revision - 1, to: review.revision })}
              </h4>
              {!hasChanges(review.diff) ? (
                <Alert>{t("edit.noChange")}</Alert>
              ) : (
                <DiffView diff={review.diff} />
              )}
            </div>
            {!review.reset && <p className="text-sm text-muted-foreground">{t("edit.applyNote")}</p>}
            {apply.error && <Alert tone="danger">{errorMessage(apply.error)}</Alert>}
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep("form")}>
                {t("common.back")}
              </Button>
              <Button
                variant={review.reset ? "destructive" : undefined}
                disabled={review.conflicts.length > 0 || apply.isPending || (!!review.reset && !confirmReset)}
                onClick={() =>
                  apply.mutate({ inputs: values, resetData: !!review.reset && confirmReset, overrides: cleaned() }, {
                    onSuccess: (job) => {
                      setJobId(job.id);
                      setStep("progress");
                    },
                  })
                }
              >
                {review.reset ? t("edit.resetApply") : t("edit.apply")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "progress" && jobId && (
        <Card className="animate-enter w-full">
          <CardHeader>
            <CardTitle>{finished === "succeeded" ? t("edit.applied") : finished ? t("deploy.failed") : t("deploy.progress")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <JobProgress jobId={jobId} onFinished={setFinished} />
            {finished && (
              <Button asChild className="justify-self-start">
                <Link href={`/app/?id=${id}`}>{t("deploy.goToApp")}</Link>
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

export default function EditPage() {
  return (
    <Suspense>
      <Edit />
    </Suspense>
  );
}
