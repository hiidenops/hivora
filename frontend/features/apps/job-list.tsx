"use client";

import type { Job } from "@/lib/api/client";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  succeeded: "text-ok",
  failed: "text-danger",
  running: "text-info",
  queued: "text-muted-foreground",
};

export function JobList({ jobs, onSelect }: { jobs: Job[]; onSelect?: (id: number) => void }) {
  const { t, lang } = useI18n();
  return (
    <ul className="divide-y text-sm">
      {jobs.map((j) => (
        <li key={j.id}>
          <button
            className="flex w-full items-center justify-between gap-3 py-2 text-left hover:bg-muted/50"
            onClick={() => onSelect?.(j.id)}
          >
            <span>
              {t(`job.kind.${j.kind}` as MessageKey)}
              {j.app_slug && <span className="ml-2 font-mono text-xs text-muted-foreground">{j.app_slug}</span>}
            </span>
            <span className="flex items-center gap-3">
              <span className={cn("text-xs font-medium", TONE[j.status])}>
                {t(`job.status.${j.status}` as MessageKey)}
              </span>
              <time className="text-xs text-muted-foreground" dateTime={j.created_at}>
                {new Date(j.created_at).toLocaleString(lang)}
              </time>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
