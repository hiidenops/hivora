"use client";

import { ExternalLink, MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/input";
import type { HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useSetHostedSiteEnabled } from "./hooks";
import { PortDialog } from "./port-dialog";
import { RemoveSiteDialog } from "./remove-site-dialog";
import { ServerNameDialog } from "./server-name-dialog";

/** One site of the host: name, port, address, and its own switch (nginx's files only:
 *  the other sites are not touched). An added site's menu: port, domain name (advanced),
 *  removal; the main site has none (it follows its app). */
export function HostedSiteRow({ appId, site, locked, stopped, onJob }: {
  appId: number;
  site: HostedSite;
  locked: boolean; // nginx 1.0.0: its sites cannot be switched yet
  stopped: boolean; // a port change or a removal recreates the container: it would start it
  onJob: (jobId: number) => void;
}) {
  const { t, errorMessage } = useI18n();
  const { can, advanced } = useSession();
  const toggle = useSetHostedSiteEnabled(appId);
  const [dialog, setDialog] = useState<"port" | "name" | "remove" | null>(null);
  const dialogProps = (d: "port" | "name" | "remove") => ({
    appId,
    site,
    onJob,
    open: dialog === d,
    onOpenChange: (o: boolean) => setDialog(o ? d : null),
  });
  const state = site.enabled ? t("hosting.on") : site.main ? t("hosting.offMain") : t("hosting.off");

  return (
    <li aria-label={site.name} className="grid gap-1 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
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
          <label className="flex items-center gap-2 text-sm" title={t("hosting.switchHelp")}>
            <Switch
              checked={site.enabled}
              disabled={!can("operator") || locked || toggle.isPending}
              aria-label={t("hosting.enabledFor", { name: site.name })}
              onChange={(e) => toggle.mutate({ siteId: site.id, enabled: e.target.checked }, { onSuccess: (job) => onJob(job.id) })}
            />
            {state}
          </label>
          {can("operator") && !site.main && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t("hosting.actions", { name: site.name })}>
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem disabled={locked || stopped} onSelect={() => setDialog("port")}>
                  {t("hosting.changePort")}
                </DropdownMenuItem>
                {advanced && (
                  <DropdownMenuItem disabled={locked} onSelect={() => setDialog("name")}>
                    {t("hosting.serverName")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={locked || stopped} className="text-danger" onSelect={() => setDialog("remove")}>
                  {t("common.delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
      {toggle.error && <p className="text-xs text-danger">{errorMessage(toggle.error)}</p>}
      {dialog === "port" && <PortDialog {...dialogProps("port")} />}
      {dialog === "name" && <ServerNameDialog {...dialogProps("name")} />}
      {dialog === "remove" && <RemoveSiteDialog {...dialogProps("remove")} />}
    </li>
  );
}
