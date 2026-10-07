"use client";

import { ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHostedSites } from "@/features/hosting/hooks";
import { SiteActions, SiteSwitch } from "@/features/hosting/site-controls";
import { ContentCard } from "@/features/sites/content-card";
import { FilesCard } from "@/features/sites/files-card";
import { siteApi, useSiteFiles } from "@/features/sites/hooks";
import { JobsCard } from "@/features/sites/jobs-card";
import { useI18n } from "@/lib/i18n";

/** One site an nginx hosts (app -> sites): its switch and actions, its content and files, on
 *  /apps/{app}/sites/{site}. `job`: one to follow on arrival (the new site's configuration). */
function HostedSiteDetail() {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const params = useSearchParams();
  const appId = Number(params.get("app") ?? 0);
  const siteId = Number(params.get("site") ?? 0);
  const router = useRouter();
  const { data: host, error, isPending } = useHostedSites(appId);
  const site = host?.sites.find((s) => s.id === siteId);
  const base = siteApi(appId, siteId);
  const { data: files } = useSiteFiles(base);
  const [jobs, setJobs] = useState<number[]>(() => (params.get("job") ? [Number(params.get("job"))] : []));

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
  const follow = (jobId: number) => setJobs([jobId]);

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
          <div className="flex items-center gap-3">
            {site.url && (
              <Button variant="outline" size="sm" asChild>
                <a href={site.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> {t("sites.open")}
                </a>
              </Button>
            )}
            <SiteSwitch appId={appId} site={site} locked={host.upgrade_required} onJob={follow} />
            <SiteActions
              appId={appId}
              site={site}
              locked={host.upgrade_required}
              stopped={host.stopped}
              onJob={follow}
              onRemoved={() => router.replace(`/app/?id=${appId}`)}
            />
          </div>
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-4 text-sm">
        {site.main && <Badge>{t("hosting.main")}</Badge>}
        {site.port !== null && <span className="font-mono text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
        {host.stopped && <span className="text-muted-foreground">{t("hosting.hostStopped")}</span>}
      </div>
      {can("operator") && files?.files.length === 0 && (
        <Alert tone="info" className="mb-6">
          {t("hosting.emptySite")}
        </Alert>
      )}
      <div className="stagger grid items-start gap-4 lg:grid-cols-2">
        <JobsCard jobs={jobs} className="animate-enter lg:col-span-2" />
        {can("operator") && <ContentCard base={base} onJob={follow} />}
        <FilesCard base={base} canEdit={can("operator")} onJob={follow} />
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
