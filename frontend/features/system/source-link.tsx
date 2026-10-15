"use client";

import { Code } from "lucide-react";

import { useHealth } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { sourceLink } from "./source";

/** This version's source code (AGPL-3.0, section 13): shown to everyone, before any login. */
export function SourceLink({ className }: { className?: string }) {
  const { t } = useI18n();
  const { data } = useHealth();
  if (!data) return null;
  return (
    <a
      href={sourceLink(data.source_url, data.version)}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline", className)}
    >
      <Code className="size-3.5" /> {t("system.source", { version: data.version })}
    </a>
  );
}
