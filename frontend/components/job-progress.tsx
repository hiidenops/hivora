"use client";

import { useEffect, useRef } from "react";

import { Alert } from "@/components/ui/alert";
import { useJob } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveJob } from "@/lib/realtime";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

/** Live progress of a job: WebSocket first, with the REST record as the source of truth. */
export function JobProgress({ jobId, onFinished, compact = false }: {
  jobId: number;
  onFinished?: (status: string) => void;
  compact?: boolean; // a shorter log (in a pop-up)
}) {
  const { t } = useI18n();
  const live = useLiveJob(jobId);
  const liveDone = !!live && TERMINAL.has(live.status);
  const { data: job, refetch } = useJob(jobId);
  const status = job && TERMINAL.has(job.status) ? job.status : (live?.status ?? job?.status ?? "queued");
  const done = TERMINAL.has(status);
  const progress = done ? 100 : Math.max(live?.progress ?? 0, job?.progress ?? 0);
  const lines = live?.lines.length ? live.lines : (job?.log ?? "").split("\n").filter(Boolean);
  const logRef = useRef<HTMLPreElement>(null);
  const notified = useRef(false);

  // Fallback polling in case a WebSocket event was missed.
  useEffect(() => {
    if (done) return;
    const timer = setInterval(() => void refetch(), 2000);
    return () => clearInterval(timer);
  }, [done, refetch]);
  useEffect(() => {
    if (liveDone) void refetch();
  }, [liveDone, refetch]);
  useEffect(() => {
    if (done && !notified.current) {
      notified.current = true;
      onFinished?.(status);
    }
  }, [done, status, onFinished]);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [lines.length]);

  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{t(`job.status.${status}` as never)}</span>
        <span className="font-mono text-xs text-muted-foreground">{progress}%</span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={
            status === "failed"
              ? "h-full bg-danger"
              : done
                ? "h-full bg-ok transition-[width,background-color] duration-700 ease-(--ease-out)"
                : "progress-active h-full bg-primary transition-[width,background-color] duration-700 ease-(--ease-out)"
          }
          style={{ width: `${progress}%` }}
        />
      </div>
      {live?.message && !done && <p className="text-sm text-muted-foreground">{live.message}</p>}
      {(job?.error ?? live?.error) && <Alert tone="danger">{job?.error ?? live?.error}</Alert>}
      <details open={status === "failed"}>
        <summary className="cursor-pointer text-sm text-muted-foreground">{t("job.log")}</summary>
        <pre
          ref={logRef}
          className={`mt-2 overflow-y-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 font-mono text-xs ${compact ? "h-40" : "h-72"}`}
        >
          {lines.join("\n")}
        </pre>
      </details>
    </div>
  );
}
