"use client";

import { ScrollText, SquareTerminal } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import type { AppDetail } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { ConsolePanel } from "./console-panel";

const LogsCard = dynamic(() => import("@/features/logs/logs-card").then((m) => m.LogsCard));

/** An app's logs and console side by side, each the full height (a wide side panel); tabs
 *  on a narrow screen. */
export function LogsAndConsole({ app, running }: { app: AppDetail; running: boolean }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"logs" | "console">("console");
  const pane = (which: "logs" | "console") =>
    cn("min-h-0 flex-col gap-3 rounded-xl border bg-card p-4", tab === which ? "flex" : "hidden", "lg:flex");
  const heading = "flex items-center gap-2 font-semibold";
  return (
    <div className="flex h-full min-h-[34rem] flex-col gap-3">
      <div role="tablist" className="inline-flex self-start rounded-md border p-0.5 lg:hidden">
        {(["logs", "console"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn("rounded px-3 py-1 text-sm transition-colors", tab === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
          >
            {t(k === "logs" ? "logs.title" : "console.title")}
          </button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
        <section className={pane("logs")} aria-label={t("logs.title")}>
          <h3 className={heading}>
            <ScrollText className="size-5" /> {t("logs.title")}
          </h3>
          <div className="min-h-0 flex-1">
            <LogsCard appId={app.id} />
          </div>
        </section>
        <section className={pane("console")} aria-label={t("console.title")}>
          <h3 className={heading}>
            <SquareTerminal className="size-5" /> {t("console.title")}
          </h3>
          <div className="min-h-0 flex-1">
            <ConsolePanel app={app} running={running} />
          </div>
        </section>
      </div>
    </div>
  );
}
