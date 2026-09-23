"use client";

import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { JobProgress } from "@/components/job-progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JobList } from "@/features/apps/job-list";
import { useAudit, useJobs } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function AuditTable() {
  const { t, lang } = useI18n();
  const { data: entries } = useAudit();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-muted-foreground">
          <tr>
            <th className="py-2 pr-4 font-medium">{t("activity.when")}</th>
            <th className="py-2 pr-4 font-medium">{t("activity.who")}</th>
            <th className="py-2 pr-4 font-medium">{t("activity.action")}</th>
            <th className="py-2 pr-4 font-medium">{t("activity.target")}</th>
            <th className="py-2 font-medium">{t("activity.result")}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {entries?.map((a) => (
            <tr key={a.id}>
              <td className="whitespace-nowrap py-2 pr-4 text-xs text-muted-foreground">
                {new Date(a.ts).toLocaleString(lang)}
              </td>
              <td className="py-2 pr-4">
                {a.username ?? "—"}
                {a.ip && <span className="ml-1 font-mono text-xs text-muted-foreground">{a.ip}</span>}
              </td>
              <td className="py-2 pr-4 font-mono text-xs">{a.action}</td>
              <td className="py-2 pr-4 font-mono text-xs">{a.target ?? ""}</td>
              <td className={cn("py-2 text-xs", a.result === "ok" || a.result === "succeeded" ? "text-ok" : "text-danger")}>
                {a.result}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ActivityPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: jobs } = useJobs();
  const [selected, setSelected] = useState<number | null>(null);

  return (
    <>
      <PageHeader title={t("activity.title")} />
      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle>{t("activity.jobs")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {selected && <JobProgress key={selected} jobId={selected} />}
            <JobList jobs={jobs ?? []} onSelect={setSelected} />
          </CardContent>
        </Card>
        {can("admin") && (
          <Card>
            <CardHeader>
              <CardTitle>{t("activity.audit")}</CardTitle>
            </CardHeader>
            <CardContent>
              <AuditTable />
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
