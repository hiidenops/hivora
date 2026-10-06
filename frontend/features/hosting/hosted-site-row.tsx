"use client";

import { ExternalLink } from "lucide-react";

import { useSession } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/input";
import type { HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useSetHostedSiteEnabled } from "./hooks";

/** One site of the host: name, port, address, and its own switch (nginx's files only:
 *  the other sites are not touched). */
export function HostedSiteRow({ appId, site, locked, onJob }: {
  appId: number;
  site: HostedSite;
  locked: boolean; // nginx 1.0.0: its sites cannot be switched yet
  onJob: (jobId: number) => void;
}) {
  const { t, errorMessage } = useI18n();
  const { can, advanced } = useSession();
  const toggle = useSetHostedSiteEnabled(appId);
  const state = site.enabled ? t("hosting.on") : site.main ? t("hosting.offMain") : t("hosting.off");

  return (
    <li aria-label={site.name} className="grid gap-1 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-medium">{site.name}</span>
          {site.main && <Badge>{t("hosting.main")}</Badge>}
          {site.port !== null && <span className="font-mono text-sm text-muted-foreground">{t("sites.portValue", { port: site.port })}</span>}
          {advanced && site.server_name && <span className="font-mono text-xs text-muted-foreground">{site.server_name}</span>}
          {site.url && (
            <a href={site.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              <ExternalLink className="size-3.5" /> {t("hosting.open")}
            </a>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm" title={t("hosting.switchHelp")}>
          <Switch
            checked={site.enabled}
            disabled={!can("operator") || locked || toggle.isPending}
            aria-label={t("hosting.enabledFor", { name: site.name })}
            onChange={(e) => toggle.mutate({ siteId: site.id, enabled: e.target.checked }, { onSuccess: (job) => onJob(job.id) })}
          />
          {state}
        </label>
      </div>
      {toggle.error && <p className="text-xs text-danger">{errorMessage(toggle.error)}</p>}
    </li>
  );
}
