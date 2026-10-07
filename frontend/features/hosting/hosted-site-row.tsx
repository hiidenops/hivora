"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import type { HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { SiteActions, SiteSwitch } from "./site-controls";

/** One site of the host: name (a link to its page), port, address, its switch and its menu. */
export function HostedSiteRow({ appId, site, locked, stopped, onJob }: {
  appId: number;
  site: HostedSite;
  locked: boolean; // nginx 1.0.0: its sites cannot be switched yet
  stopped: boolean; // a port change or a removal recreates the container: it would start it
  onJob: (jobId: number) => void;
}) {
  const { t } = useI18n();
  const { advanced } = useSession();

  return (
    <li aria-label={site.name} className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Link href={`/app/site/?app=${appId}&site=${site.id}`} className="font-medium hover:underline">
          {site.name}
        </Link>
        {site.main && <Badge>{t("hosting.main")}</Badge>}
        {site.port !== null && <span className="font-mono text-sm text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
        {advanced && site.server_name && <span className="font-mono text-xs text-muted-foreground">{site.server_name}</span>}
        {site.url && (
          <a href={site.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ExternalLink className="size-3.5" /> {t("hosting.open")}
          </a>
        )}
      </div>
      <div className="flex items-center gap-2">
        <SiteSwitch appId={appId} site={site} locked={locked} onJob={onJob} />
        <SiteActions appId={appId} site={site} locked={locked} stopped={stopped} onJob={onJob} />
      </div>
    </li>
  );
}
