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
            className="grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted/60"
            onClick={() => onSelect?.(j.id)}
          >
            <span className="truncate">{t(`job.kind.${j.kind}` as MessageKey)}</span>
            <span className={cn("text-xs font-medium", TONE[j.status])}>
              {t(`job.status.${j.status}` as MessageKey)}
            </span>
            <span className="truncate font-mono text-xs text-muted-foreground">{j.app_slug}</span>
            <time className="text-xs text-muted-foreground" dateTime={j.created_at}>
              {new Date(j.created_at).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" })}
            </time>
          </button>
        </li>
      ))}
    </ul>
  );
}
