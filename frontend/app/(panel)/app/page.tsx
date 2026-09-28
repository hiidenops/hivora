"use client";

import { Pencil } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
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
const PythonCodeCard = dynamic(() => import("@/features/apps/python-code-card").then((m) => m.PythonCodeCard));
const TasksCard = dynamic(() => import("@/features/tasks/tasks-card").then((m) => m.TasksCard));
const BackupsCard = dynamic(() => import("@/features/backups/backups-card").then((m) => m.BackupsCard));
const UpgradeBanner = dynamic(() => import("@/features/apps/change-dialog").then((m) => m.UpgradeBanner));
const AdvancedCards = dynamic(() => import("@/features/apps/advanced-cards").then((m) => m.AdvancedCards));
import { ApiError } from "@/lib/api/client";
import { useApp, useJob } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function AppDetail() {
  const { t, errorMessage } = useI18n();
  const router = useRouter();
  const { advanced, can } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: app, error } = useApp(id);
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
        {can("operator") && app.template && <UpgradeBanner appId={app.id} onJob={setActiveJob} />}
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
        {can("operator") && app.python && <PythonCodeCard appId={app.id} onJob={setActiveJob} />}
        {can("operator") && <BackupsCard appId={app.id} onJob={setActiveJob} />}
        {can("operator") && <TasksCard appId={app.id} />}
        {can("operator") && <LogsCard appId={app.id} />}
        {can("operator") && (
          <ConsolePanel app={app} running={["healthy", "starting", "degraded"].includes(status)} />
        )}
        {advanced && <AdvancedCards app={app} onJob={setActiveJob} />}
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
