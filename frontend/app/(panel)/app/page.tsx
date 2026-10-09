"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AppActions } from "@/features/apps/app-actions";
import { AppMenu } from "@/features/apps/app-menu";
import { AppUsage } from "@/features/apps/app-usage";
import { StatusHero } from "@/features/apps/status-hero";
import { GamePanel } from "@/features/games/game-panel";
import { hostsSites } from "@/features/hosting/server";

// Only VPN apps need it: loaded on demand (page budget).
const VpnCard = dynamic(() => import("@/features/vpn/vpn-card").then((m) => m.VpnCard));
const UpgradeBanner = dynamic(() => import("@/features/apps/change-dialog").then((m) => m.UpgradeBanner));
const HostedSitesCard = dynamic(() => import("@/features/hosting/hosted-sites-card").then((m) => m.HostedSitesCard));
import { ApiError } from "@/lib/api/client";
import { useApp } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function AppDetail() {
  const { t, errorMessage } = useI18n();
  const router = useRouter();
  const { can } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: app, error } = useApp(id);
  const setActiveJob = useTrackJob(); // followed in a pop-up
  const [removing, setRemoving] = useState(false);
  const status = useLiveStatus(app?.slug ?? "", app?.status ?? "missing");
  const running = ["healthy", "starting", "degraded"].includes(status);
  // Removal deletes the app before its job ends: a 404 then means "removed", not an error
  // (the job card, which redirects when the job ends, would be gone with the page).
  const removed = removing && error instanceof ApiError && error.status === 404;
  useEffect(() => {
    if (removed) router.replace("/");
  }, [removed, router]);

  if (removed) return null;
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
            <AppActions id={app.id} status={status} onJob={setActiveJob} />
            <AppMenu
              app={app}
              running={running}
              onJob={setActiveJob}
              onRemoving={(jobId) => {
                setRemoving(true);
                setActiveJob(jobId, (s) => s === "succeeded" && router.replace("/"));
              }}
            />
          </>
        }
      />
      <div className="stagger grid items-start gap-4 lg:grid-cols-2">
        <StatusHero app={app} status={status} />
        {can("operator") && app.template && <UpgradeBanner appId={app.id} onJob={setActiveJob} />}
        {hostsSites(app.template) && <HostedSitesCard appId={app.id} template={app.template!} hosting={app.hosting} onJob={setActiveJob} />}
        {["healthy", "starting", "degraded"].includes(status) && <AppUsage slug={app.slug} />}
        {app.game && (
          <GamePanel
            appId={app.id}
            caps={app.game}
            running={running}
            onJob={setActiveJob}
          />
        )}
        {app.vpn && can("operator") && <VpnCard appId={app.id} onJob={setActiveJob} />}
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
