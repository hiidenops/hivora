"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { JobProgress } from "@/components/job-progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { HostCharts } from "@/features/activity/host-charts";
import { JobList } from "@/features/apps/job-list";
import { api } from "@/lib/api/client";
import { keys, useAudit, useJobs } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// How many rows each list shows; "all": the server's most (jobs 500, audit 1000).
const COUNTS = [10, 20, 50] as const;
const ALL = { jobs: 500, audit: 1000 };

function CountSelect({ value, all, onChange, label }: { value: number; all: number; onChange: (n: number) => void; label: string }) {
  const { t } = useI18n();
  return (
    <label className="flex items-center gap-2 text-sm font-normal text-muted-foreground">
      {t("activity.show")}
      <Select aria-label={label} className="h-8 w-auto py-0 text-sm" value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {COUNTS.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
        <option value={all}>{t("activity.all")}</option>
      </Select>
    </label>
  );
}

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
      loading={clear.isPending} disabled={clear.isPending}
      onClick={() => window.confirm(t(confirmKey)) && clear.mutate()}
    >
      <Trash2 /> {t("activity.clear")}
    </Button>
  );
}

function AuditTable({ limit }: { limit: number }) {
  const { t, lang } = useI18n();
  const { data: entries } = useAudit(limit);
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
  const [jobCount, setJobCount] = useState(10);
  const [auditCount, setAuditCount] = useState(10);
  const { data: jobs } = useJobs(undefined, jobCount);
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
            <span className="flex flex-wrap items-center gap-3">
              <CountSelect value={jobCount} all={ALL.jobs} onChange={setJobCount} label={t("activity.showJobs")} />
              {can("admin") && <ClearButton path="/jobs" confirmKey="activity.clearJobsConfirm" queryKey={keys.jobs} />}
            </span>
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
              <span className="flex flex-wrap items-center gap-3">
                <CountSelect value={auditCount} all={ALL.audit} onChange={setAuditCount} label={t("activity.showAudit")} />
                <ClearButton path="/audit" confirmKey="activity.clearAuditConfirm" queryKey={keys.audit} />
              </span>
            </CardHeader>
            <CardContent>
              <AuditTable limit={auditCount} />
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
