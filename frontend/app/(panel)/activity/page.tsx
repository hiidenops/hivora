"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { JobProgress } from "@/components/job-progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { HostCharts } from "@/features/activity/host-charts";
import { JobList } from "@/features/apps/job-list";
import { api } from "@/lib/api/client";
import { keys, useAudit, useJobs } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** Admin-only "clear" button with a confirmation. */
function ClearButton({ path, confirmKey, queryKey }: { path: string; confirmKey: MessageKey; queryKey: readonly string[] }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const clear = useMutation({
    mutationFn: () => api<{ deleted: number }>(path, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={clear.isPending}
      onClick={() => window.confirm(t(confirmKey)) && clear.mutate()}
    >
      <Trash2 /> {t("activity.clear")}
    </Button>
  );
}

function AuditTable() {
  const { t, lang } = useI18n();
  const { data: entries } = useAudit();
  return (
    <Table>
      <THead>
        <tr>
          <Th>{t("activity.when")}</Th>
          <Th>{t("activity.who")}</Th>
          <Th>{t("activity.action")}</Th>
          <Th>{t("activity.target")}</Th>
          <Th>{t("activity.result")}</Th>
        </tr>
      </THead>
      <TBody>
        {entries?.map((a) => (
          <Tr key={a.id}>
            <Td className="whitespace-nowrap text-xs text-muted-foreground">{new Date(a.ts).toLocaleString(lang)}</Td>
            <Td>
              {a.username ?? "—"}
              {a.ip && <span className="ml-1 font-mono text-xs text-muted-foreground">{a.ip}</span>}
            </Td>
            <Td mono>{a.action}</Td>
            <Td mono>{a.target ?? ""}</Td>
            <Td className={cn("text-xs", a.result === "ok" || a.result === "succeeded" ? "text-ok" : "text-danger")}>{a.result}</Td>
          </Tr>
        ))}
      </TBody>
    </Table>
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
      <div className="stagger grid gap-4">
        <section aria-label={t("metrics.title")}>
          <HostCharts />
        </section>
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>{t("activity.jobs")}</CardTitle>
            {can("admin") && <ClearButton path="/jobs" confirmKey="activity.clearJobsConfirm" queryKey={keys.jobs} />}
          </CardHeader>
          <CardContent className="grid gap-4">
            {selected && <JobProgress key={selected} jobId={selected} />}
            <JobList jobs={jobs ?? []} onSelect={setSelected} />
          </CardContent>
        </Card>
        {can("admin") && (
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>{t("activity.audit")}</CardTitle>
              <ClearButton path="/audit" confirmKey="activity.clearAuditConfirm" queryKey={keys.audit} />
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
