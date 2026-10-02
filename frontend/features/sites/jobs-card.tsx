"use client";

import { JobProgress } from "@/components/job-progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

/** The jobs started from a sites page, followed live. */
export function JobsCard({ jobs, className }: { jobs: number[]; className?: string }) {
  const { t } = useI18n();
  if (jobs.length === 0) return null;
  return (
    <Card className={className ?? "animate-enter"}>
      <CardHeader>
        <CardTitle>{t("sites.tracking")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        {jobs.map((id) => (
          <TrackedJob key={id} jobId={id} />
        ))}
      </CardContent>
    </Card>
  );
}
