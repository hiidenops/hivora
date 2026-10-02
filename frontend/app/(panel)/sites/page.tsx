"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { JobProgress } from "@/components/job-progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TileSkeletons } from "@/components/ui/skeleton";
import { CreateSiteDialog } from "@/features/sites/create-site-dialog";
import { useSites } from "@/features/sites/hooks";
import { SiteCard } from "@/features/sites/site-card";
import { useJob } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";

function TrackedJob({ jobId }: { jobId: number }) {
  const { t } = useI18n();
  const { data: job } = useJob(jobId);
  return (
    <div className="grid gap-2">
      <span className="text-sm font-medium">{job ? t(`job.kind.${job.kind}` as MessageKey) : t("common.loading")}</span>
      <JobProgress jobId={jobId} />
    </div>
  );
}

export default function SitesPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: sites, isPending } = useSites();
  const [jobs, setJobs] = useState<number[]>([]);
  const create = <CreateSiteDialog trigger={<Button><Plus /> {t("sites.create")}</Button>} onJobs={setJobs} />;

  return (
    <>
      <PageHeader title={t("sites.title")} actions={can("operator") && create} />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("sites.intro")}</p>
      {jobs.length > 0 && (
        <Card className="animate-enter mb-6">
          <CardHeader>
            <CardTitle>{t("sites.tracking")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {jobs.map((id) => (
              <TrackedJob key={id} jobId={id} />
            ))}
          </CardContent>
        </Card>
      )}
      {isPending && <TileSkeletons label={t("common.loading")} count={2} />}
      {sites?.length === 0 && (
        <div className="surface grid justify-items-start gap-3 rounded-xl border p-6">
          <p className="text-muted-foreground">{t("sites.empty")}</p>
          {can("operator") && create}
        </div>
      )}
      <div className="stagger grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
        {sites?.map((s) => (
          <SiteCard key={s.id} site={s} onJob={(id) => setJobs([id])} />
        ))}
      </div>
    </>
  );
}
