"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function CodeView({ code, className }: { code: string; className?: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (plain HTTP): text stays selectable */
    }
  };
  return (
    <div className={cn("relative min-w-0 rounded-md border bg-muted", className)}>
      <Button variant="ghost" size="sm" className="absolute right-1 top-1" onClick={copy}>
        {copied ? <Check /> : <Copy />} {copied ? t("common.copied") : t("common.copy")}
      </Button>
      <pre className="max-h-96 overflow-auto p-3 pr-24 font-mono text-xs leading-relaxed">{code}</pre>
    </div>
  );
}
