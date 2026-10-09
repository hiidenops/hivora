"use client";

import { MoreHorizontal, Pencil } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
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
import { useServerName } from "./server";

// Loaded when opened: a site's page stays light.
const PortDialog = dynamic(() => import("./port-dialog").then((m) => m.PortDialog));
const RemoveSiteDialog = dynamic(() => import("./remove-site-dialog").then((m) => m.RemoveSiteDialog));
const ServerNameDialog = dynamic(() => import("./server-name-dialog").then((m) => m.ServerNameDialog));

type Controls = {
  appId: number;
  site: HostedSite;
  locked: boolean; // nginx 1.0.0: its sites cannot be changed yet
  onJob: (jobId: number) => void;
};

/** A site's own switch and its state (nginx's files only: the other sites are not touched). */
export function SiteSwitch({ appId, site, locked, onJob }: Controls) {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const server = useServerName();
  const toggle = useSetHostedSiteEnabled(appId);
  const state = site.enabled ? t("hosting.on") : site.main ? t("hosting.offMain") : t("hosting.off");
  return (
    <span className="grid gap-1">
      <label className="flex items-center gap-2 text-sm" title={t("hosting.switchHelp", { server })}>
        <Switch
          checked={site.enabled}
          disabled={!can("operator") || locked || toggle.isPending}
          aria-label={t("hosting.enabledFor", { name: site.name })}
          onChange={(e) => toggle.mutate({ siteId: site.id, enabled: e.target.checked }, { onSuccess: (job) => onJob(job.id) })}
        />
        {state}
      </label>
      {toggle.error && <span className="text-xs text-danger">{errorMessage(toggle.error)}</span>}
    </span>
  );
}

/** A site's port, as a button that changes it (any site's, the main one's is its app's web
 *  port); plain text for a viewer. */
export function SitePort({ appId, site, locked, stopped, onJob }: Controls & { stopped: boolean }) {
  const { t } = useI18n();
  const { can } = useSession();
  const [open, setOpen] = useState(false);
  if (site.port === null) return null;
  const text = t("sites.portValue", { port: site.port });
  if (!can("operator")) return <span className="font-mono text-sm text-muted-foreground">{text}</span>;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 px-2 font-mono text-muted-foreground"
        disabled={locked || stopped}
        aria-label={t("hosting.changePortOf", { name: site.name, port: site.port })}
        title={t("hosting.changePort")}
        onClick={() => setOpen(true)}
      >
        {text} <Pencil className="size-3.5" />
      </Button>
      {open && <PortDialog appId={appId} site={site} open={open} onOpenChange={setOpen} onJob={onJob} />}
    </>
  );
}

/** A site's menu: port; for an added site, its domain name (advanced mode) and removal (the
 *  main site follows its app). None for a viewer. `onRemoved`: after the removal (default: onJob). */
export function SiteActions({ appId, site, locked, stopped, onJob, onRemoved = onJob }: Controls & {
  stopped: boolean; // a port change or a removal recreates the container: it would start it
  onRemoved?: (jobId: number) => void;
}) {
  const { t } = useI18n();
  const { can, advanced } = useSession();
  const [dialog, setDialog] = useState<"port" | "name" | "remove" | null>(null);
  if (!can("operator")) return null;
  const dialogProps = (d: "port" | "name" | "remove") => ({
    appId,
    site,
    onJob: d === "remove" ? onRemoved : onJob,
    open: dialog === d,
    onOpenChange: (o: boolean) => setDialog(o ? d : null),
  });

  return (
    <>
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
          {advanced && !site.main && (
            <DropdownMenuItem disabled={locked} onSelect={() => setDialog("name")}>
              {t("hosting.serverName")}
            </DropdownMenuItem>
          )}
          {!site.main && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled={locked || stopped} className="text-danger" onSelect={() => setDialog("remove")}>
                {t("common.delete")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {dialog === "port" && <PortDialog {...dialogProps("port")} />}
      {dialog === "name" && <ServerNameDialog {...dialogProps("name")} />}
      {dialog === "remove" && <RemoveSiteDialog {...dialogProps("remove")} />}
    </>
  );
}
