"use client";

import { Globe, Settings2 } from "lucide-react";
import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import type { Site } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

import { EnabledSwitch } from "./enabled-switch";

/** A site in the list: live status, port, on/off, and its app settings. */
export function SiteCard({ site, onJob }: { site: Site; onJob: (jobId: number) => void }) {
  const { t } = useI18n();
  const status = useLiveStatus(site.slug, site.status);

  return (
    <article aria-label={site.name} className="surface grid gap-4 rounded-xl border p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Globe className="size-5 text-muted-foreground" /> {site.name}
          </h2>
          {site.port !== null && <span className="font-mono text-sm text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
        </div>
        {site.deployed ? <StatusBadge status={status} /> : <span className="text-xs text-muted-foreground">{t("sites.deploying")}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <EnabledSwitch site={site} onJob={onJob} />
        <Link href={`/app/?id=${site.id}`} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <Settings2 className="size-4" /> {t("sites.appSettings")}
        </Link>
      </div>
    </article>
  );
}
