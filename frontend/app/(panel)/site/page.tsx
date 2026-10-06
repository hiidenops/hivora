"use client";

import { ExternalLink, Settings2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ContentCard } from "@/features/sites/content-card";
import { EnabledSwitch } from "@/features/sites/enabled-switch";
import { FilesCard } from "@/features/sites/files-card";
import { siteApi, useSites } from "@/features/sites/hooks";
import { JobsCard } from "@/features/sites/jobs-card";
import { useApp } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function SiteDetail() {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: sites, isPending, error } = useSites();
  const site = sites?.find((s) => s.id === id);
  const { data: app } = useApp(site?.deployed ? id : 0); // the URL to open it
  const status = useLiveStatus(site?.slug ?? "", site?.status ?? "missing");
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
  if (!site) return <Alert tone="danger">{t("error.site_not_found")}</Alert>;
  const url = app?.access.web ?? Object.values(app?.access ?? {})[0];

  return (
    <>
      <PageHeader
        title={site.name}
        actions={
          <>
            {url && (
              <Button variant="outline" size="sm" asChild>
                <a href={url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> {t("sites.open")}
                </a>
              </Button>
            )}
            <Button variant="outline" size="sm" asChild>
              <Link href={`/app/?id=${site.id}`}>
                <Settings2 /> {t("sites.appSettings")}
              </Link>
            </Button>
          </>
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-6">
        {site.deployed ? <StatusBadge status={status} /> : <span className="text-sm text-muted-foreground">{t("sites.deploying")}</span>}
        {site.port !== null && <span className="font-mono text-sm text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
        <EnabledSwitch site={site} onJob={(jobId) => setJobs([jobId])} />
      </div>
      <div className="stagger grid items-start gap-4 lg:grid-cols-2">
        <JobsCard jobs={jobs} className="animate-enter lg:col-span-2" />
        {can("operator") && <ContentCard base={siteApi(site.id)} onJob={(jobId) => setJobs([jobId])} />}
        <FilesCard base={siteApi(site.id)} canEdit={can("operator")} onJob={(jobId) => setJobs([jobId])} />
      </div>
    </>
  );
}

export default function SitePage() {
  return (
    <Suspense>
      <SiteDetail />
    </Suspense>
  );
}
