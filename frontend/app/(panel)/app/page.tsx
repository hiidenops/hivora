"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { JobProgress } from "@/components/job-progress";
import { StatusBadge } from "@/components/status-badge";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AppActions } from "@/features/apps/app-actions";
import { JobList } from "@/features/apps/job-list";
import { RemoveDialog } from "@/features/apps/remove-dialog";
import { ApiError } from "@/lib/api/client";
import { useApp, useAppCompose, useJob, useJobs, useRevisions } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function AppDetail() {
  const { t, lang, errorMessage } = useI18n();
  const router = useRouter();
  const { advanced, can } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: app, error } = useApp(id);
  const { data: jobs } = useJobs(id);
  const { data: compose } = useAppCompose(id, advanced && !!app);
  const { data: revisions } = useRevisions(id, advanced && !!app);
  const [activeJob, setActiveJob] = useState<number | null>(null);
  const [removing, setRemoving] = useState(false);
  const { data: active } = useJob(activeJob);
  const status = useLiveStatus(app?.slug ?? "", app?.status ?? "missing");

  if (error) {
    return <Alert tone="danger">{error instanceof ApiError && error.status === 404 ? t("app.notFound") : errorMessage(error)}</Alert>;
  }
  if (!app) {
    return (
      <div role="status" aria-label={t("common.loading")} className="grid gap-4">
        <Skeleton className="h-10 w-1/3" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            <AppIcon src={app.icon_url} name={app.name} />
            {app.name}
            <StatusBadge status={status} drift={app.drift} />
          </span>
        }
        actions={
          <>
            <AppActions id={app.id} status={status} onJob={setActiveJob} />
            {can("operator") && (
              <RemoveDialog
                id={app.id}
                name={app.name}
                onJob={(jobId) => {
                  setRemoving(true);
                  setActiveJob(jobId);
                }}
              />
            )}
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        {activeJob && (
          <Card className="animate-enter lg:col-span-2">
            <CardHeader>
              <CardTitle>{active ? t(`job.kind.${active.kind}` as MessageKey) : t("common.loading")}</CardTitle>
            </CardHeader>
            <CardContent>
              <JobProgress
                jobId={activeJob}
                onFinished={(s) => removing && s === "succeeded" && router.replace("/")}
              />
            </CardContent>
          </Card>
        )}
        <Card>
          <CardHeader>
            <CardTitle>{t("app.status")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">{t("app.desired")}</dt>
              <dd>{app.desired_state === "running" ? t("app.running") : t("app.stoppedWanted")}</dd>
              <dt className="text-muted-foreground">{t("app.revision")}</dt>
              <dd className="font-mono">{app.revision ?? "—"}</dd>
            </dl>
            <h4 className="mb-2 mt-5 text-sm font-medium">{t("app.containers")}</h4>
            {app.containers.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("common.none")}</p>
            ) : (
              <ul className="grid gap-1 text-sm">
                {app.containers.map((c) => (
                  <li key={c.id} className="flex justify-between gap-2">
                    <span className="font-mono text-xs">{c.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {c.state}
                      {c.health !== "none" && ` · ${c.health}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("app.jobs")}</CardTitle>
          </CardHeader>
          <CardContent>
            <JobList jobs={(jobs ?? []).slice(0, 8)} onSelect={setActiveJob} />
          </CardContent>
        </Card>
        {advanced && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>{t("app.ports")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-1 font-mono text-xs">
                  {app.ports.map((p) => (
                    <li key={`${p.service}-${p.container_port}-${p.protocol}`}>
                      {p.host_port ? `${p.host_ip ?? "0.0.0.0"}:${p.host_port} → ` : ""}
                      {p.service}:{p.container_port}/{p.protocol} ({p.exposure})
                    </li>
                  ))}
                </ul>
                <h4 className="mb-2 mt-4 text-sm font-medium">{t("app.volumes")}</h4>
                <ul className="grid gap-1 font-mono text-xs">
                  {app.volumes.map((v) => (
                    <li key={v}>{v}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t("app.revisions")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y text-sm">
                  {revisions?.map((r) => (
                    <li key={r.id} className="flex justify-between py-2">
                      <span className="font-mono">#{r.number}</span>
                      <span className="text-xs text-muted-foreground">
                        {r.status} · {new Date(r.created_at).toLocaleString(lang)}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
            {compose && (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle>{t("app.compose")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CodeView code={compose.compose_yaml} />
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </>
  );
}

export default function AppPage() {
  return (
    <Suspense>
      <AppDetail />
    </Suspense>
  );
}
