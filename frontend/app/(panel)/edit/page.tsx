"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { DiffView } from "@/components/diff-view";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
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
  const { t, errorMessage } = useI18n();
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

  const form = settings?.form as { basic?: FieldDef[]; advanced?: FieldDef[] } | undefined;
  const basic = useMemo(() => form?.basic ?? [], [form]);
  const advancedFields = useMemo(() => form?.advanced ?? [], [form]);
  useEffect(() => {
    if (settings) setValues(settings.values);
  }, [settings]);

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
        <Card className="max-w-2xl">
          <CardContent className="grid gap-6 pt-5">
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
                <summary className="cursor-pointer text-sm font-medium">{t("deploy.advanced")}</summary>
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
            {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
            <div className="flex gap-2">
              <Button variant="outline" asChild>
                <Link href={`/app/?id=${id}`}>{t("common.cancel")}</Link>
              </Button>
              <Button
                disabled={plan.isPending}
                onClick={() =>
                  plan.mutate(values, {
                    onSuccess: (p) => {
                      setReview(p);
                      setStep("review");
                    },
                  })
                }
              >
                {t("edit.review")}
              </Button>
            </div>
          </CardContent>
        </Card>
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
            <p className="text-sm text-muted-foreground">{t("edit.applyNote")}</p>
            {apply.error && <Alert tone="danger">{errorMessage(apply.error)}</Alert>}
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep("form")}>
                {t("common.back")}
              </Button>
              <Button
                disabled={review.conflicts.length > 0 || apply.isPending}
                onClick={() =>
                  apply.mutate(values, {
                    onSuccess: (job) => {
                      setJobId(job.id);
                      setStep("progress");
                    },
                  })
                }
              >
                {t("edit.apply")}
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
