"use client";

import { Database, ExternalLink, Plus } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/app-shell";
import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import type { AppDetail } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { CopyAddress } from "./status-hero";

/** A database's page: how to reach it (from its zone and linked tools, and from the network
 *  once opened), the tools linked to it, and those to install for it (form prefilled). */
export function DatabaseCard({ app }: { app: AppDetail }) {
  const { t } = useI18n();
  const { can } = useSession();
  const db = app.database!;
  const open = app.ports.find((p) => p.container_port === db.port && p.host_port && p.exposure !== "internal");
  const ip = open?.host_ip && open.host_ip !== "0.0.0.0" ? open.host_ip : typeof window === "undefined" ? "" : window.location.hostname;
  const rows: [string, string | null | undefined][] = [
    [t("db.host"), db.host],
    [t("db.port"), String(db.port)],
    [t("db.database"), db.database],
    [t("db.user"), db.user],
    [t("db.network"), open ? `${ip}:${open.host_port}` : null],
  ];
  return (
    <CollapsibleCard
      storageKey="app.database"
      defaultOpen
      title={
        <>
          <Database className="size-5" /> {t("db.title")}
        </>
      }
    >
      <div className="grid gap-4 text-sm">
        <p className="text-muted-foreground">{t("db.help")}</p>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
          {rows.map(([label, value]) =>
            value ? (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd>
                  <CopyAddress value={value} />
                </dd>
              </div>
            ) : null,
          )}
        </dl>
        <div className="flex flex-wrap gap-2">
          {db.tools.map((tool) => (
            <Button key={tool.id} size="sm" asChild>
              {tool.web ? (
                <a href={tool.web} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> {t("db.openIn", { tool: tool.name })}
                </a>
              ) : (
                <Link href={`/app/?id=${tool.id}`}>{t("db.openIn", { tool: tool.name })}</Link>
              )}
            </Button>
          ))}
          {can("operator") &&
            db.installable.map((tpl) => (
              <Button key={tpl.slug} size="sm" variant="outline" asChild>
                <Link href={`/deploy/?template=${tpl.slug}&database=${encodeURIComponent(app.slug)}`}>
                  <Plus /> {t("db.install", { tool: tpl.name })}
                </Link>
              </Button>
            ))}
        </div>
      </div>
    </CollapsibleCard>
  );
}
