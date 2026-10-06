"use client";

import { ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHostedSites } from "@/features/hosting/hooks";
import { ContentCard } from "@/features/sites/content-card";
import { FilesCard } from "@/features/sites/files-card";
import { siteApi } from "@/features/sites/hooks";
import { JobsCard } from "@/features/sites/jobs-card";
import { useI18n } from "@/lib/i18n";

/** One site an nginx hosts (app -> sites): its content and files, on /apps/{app}/sites/{site}. */
function HostedSiteDetail() {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const params = useSearchParams();
  const appId = Number(params.get("app") ?? 0);
  const siteId = Number(params.get("site") ?? 0);
  const { data: host, error, isPending } = useHostedSites(appId);
  const site = host?.sites.find((s) => s.id === siteId);
  const [jobs, setJobs] = useState<number[]>([]);

  if (error) return <Alert tone="danger">{errorMessage(error)}</Alert>;
  if (isPending) {
    return (
      <div role="status" aria-label={t("common.loading")} className="grid gap-4">
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (!host || !site) return <Alert tone="danger">{t("error.site_not_found")}</Alert>;
  const base = siteApi(appId, siteId);
  const state = site.enabled ? t("hosting.on") : site.main ? t("hosting.offMain") : t("hosting.off");

  return (
    <>
      <nav aria-label={t("hosting.breadcrumb")} className="mb-2 flex items-center gap-1 text-sm text-muted-foreground">
        <Link href={`/app/?id=${appId}`} className="hover:text-foreground">
          {host.name}
        </Link>
        <ChevronRight className="size-3.5" />
        <span aria-current="page">{site.name}</span>
      </nav>
      <PageHeader
        title={site.name}
        actions={
          site.url && (
            <Button variant="outline" size="sm" asChild>
              <a href={site.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink /> {t("sites.open")}
              </a>
            </Button>
          )
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-4 text-sm">
        {site.main && <Badge>{t("hosting.main")}</Badge>}
        {site.port !== null && <span className="font-mono text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
        <span>{state}</span>
        {host.stopped && <span className="text-muted-foreground">{t("hosting.hostStopped")}</span>}
      </div>
      <div className="stagger grid items-start gap-4 lg:grid-cols-2">
        <JobsCard jobs={jobs} className="animate-enter lg:col-span-2" />
        {can("operator") && <ContentCard base={base} onJob={(jobId) => setJobs([jobId])} />}
        <FilesCard base={base} canEdit={can("operator")} onJob={(jobId) => setJobs([jobId])} />
      </div>
    </>
  );
}

export default function HostedSitePage() {
  return (
    <Suspense>
      <HostedSiteDetail />
    </Suspense>
  );
}
