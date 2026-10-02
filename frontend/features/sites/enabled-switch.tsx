"use client";

import { useSession } from "@/components/app-shell";
import { Switch } from "@/components/ui/input";
import type { Site } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useSetSiteEnabled } from "./hooks";

/** Start or stop a site; available once its first deploy has run. */
export function EnabledSwitch({ site, onJob }: { site: Site; onJob: (jobId: number) => void }) {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const toggle = useSetSiteEnabled();
  const ready = site.deployed && can("operator");

  return (
    <div className="grid gap-1">
      <label className="flex items-center gap-2 text-sm font-medium" title={site.deployed ? undefined : t("sites.notDeployedYet")}>
        <Switch
          checked={site.enabled}
          disabled={!ready || toggle.isPending}
          aria-label={t("sites.enabledFor", { name: site.name })}
          onChange={(e) => toggle.mutate({ id: site.id, enabled: e.target.checked }, { onSuccess: (job) => onJob(job.id) })}
        />
        {t(site.enabled ? "sites.enabled" : "sites.disabled")}
      </label>
      {toggle.error && <p className="text-xs text-danger">{errorMessage(toggle.error)}</p>}
    </div>
  );
}
