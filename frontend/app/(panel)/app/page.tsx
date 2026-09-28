"use client";

import { Pencil } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AppActions } from "@/features/apps/app-actions";
import { AppUsage } from "@/features/apps/app-usage";
import { StatusHero } from "@/features/apps/status-hero";
import { ConsolePanel } from "@/features/console/console-panel";
import { GamePanel } from "@/features/games/game-panel";
import { RemoveDialog } from "@/features/apps/remove-dialog";
import { ZoneSelect } from "@/features/zones/zone-select";

// Only VPN apps need it: loaded on demand (page budget).
const VpnCard = dynamic(() => import("@/features/vpn/vpn-card").then((m) => m.VpnCard));
const LogsCard = dynamic(() => import("@/features/logs/logs-card").then((m) => m.LogsCard));
import { ApiError } from "@/lib/api/client";
import { useApp, useAppCompose, useJob, useRevisions } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function AppDetail() {
  const { t, lang, errorMessage } = useI18n();
  const router = useRouter();
  const { advanced, can } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: app, error } = useApp(id);
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
            {app.name}
          </span>
        }
        actions={
          <>
            {can("operator") && app.template && <ZoneSelect appId={app.id} zoneId={app.zone_id} onJob={setActiveJob} />}
            <AppActions id={app.id} status={status} onJob={setActiveJob} />
            {can("operator") && app.template && (
              <Button variant="outline" size="sm" asChild>
                <Link href={`/edit/?id=${app.id}`}>
                  <Pencil /> {t("edit.button")}
                </Link>
              </Button>
            )}
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
      <div className="stagger grid items-start gap-4 lg:grid-cols-2">
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
        <StatusHero app={app} status={status} />
        {["healthy", "starting", "degraded"].includes(status) && <AppUsage slug={app.slug} />}
        {app.game && (
          <GamePanel
            appId={app.id}
            caps={app.game}
            running={["healthy", "starting", "degraded"].includes(status)}
            onJob={setActiveJob}
          />
        )}
        {app.vpn && can("operator") && <VpnCard appId={app.id} onJob={setActiveJob} />}
        {can("operator") && <LogsCard appId={app.id} />}
        {can("operator") && (
          <ConsolePanel app={app} running={["healthy", "starting", "degraded"].includes(status)} />
        )}
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
                <h4 className="mb-2 mt-4 text-sm font-medium">{t("app.containers")}</h4>
                <ul className="grid gap-1 text-xs">
                  {app.containers.map((c) => (
                    <li key={c.id} className="flex justify-between gap-2">
                      <span className="font-mono">{c.name}</span>
                      <span className="text-muted-foreground">
                        {c.state}
                        {c.health !== "none" && ` · ${c.health}`}
                      </span>
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
