"use client";

import { Check, Copy } from "lucide-react";

import { useCopy } from "@/components/copy";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function CodeView({ code, className }: { code: string; className?: string }) {
  const { t } = useI18n();
  const { copied, copy, bubble } = useCopy();
  return (
    <div className={cn("relative min-w-0 rounded-md border bg-muted", className)}>
      <div className="absolute right-1 top-1">
        {bubble}
        <Button variant="ghost" size="sm" onClick={() => copy(code)}>
          {copied ? <Check /> : <Copy />} {copied ? t("common.copied") : t("common.copy")}
        </Button>
      </div>
      <pre className="max-h-96 overflow-auto p-3 pr-24 font-mono text-xs leading-relaxed">{code}</pre>
    </div>
  );
}
