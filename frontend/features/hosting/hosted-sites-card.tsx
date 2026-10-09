"use client";

import { Globe } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n";

import { AddSiteDialog } from "./add-site-dialog";
import { ConfigStatus } from "./config-status";
import { useEnableHosting, useHostedSites } from "./hooks";
import { HostedSiteRow } from "./hosted-site-row";
import { SITE_SERVERS, ServerName } from "./server";

/** The sites a web server app hosts (nginx, Apache; app -> sites): each on its own port,
 *  each with its own switch; "Add a site" first shows what the change does. `title`: the
 *  server's name, linked to its page (the sites index), instead of "Sites" (its own page). */
export function HostedSitesCard({ appId, template, hosting, title: name, onJob }: {
  appId: number;
  template: string; // its catalog template: nginx, httpd
  hosting: boolean; // the app's flag: no request for a server that hosts no sites
  title?: string;
  onJob: (jobId: number) => void;
}) {
  const known = SITE_SERVERS[template] ?? SITE_SERVERS.nginx;
  const { t, errorMessage } = useI18n();
  const { can, advanced } = useSession();
  const { data: host, error, isPending, notHost } = useHostedSites(appId, hosting);
  const enable = useEnableHosting(appId);
  const operator = can("operator");
  const server = host?.server ?? known.label;

  const title = (
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <Globe className="size-5" />{" "}
        {name ? (
          <Link href={`/app/?id=${appId}`} className="hover:underline">
            {name}
          </Link>
        ) : (
          t("hosting.title")
        )}
      </CardTitle>
    </CardHeader>
  );

  if (notHost) {
    return (
      <Card className="lg:col-span-2">
        {title}
        <CardContent className="grid justify-items-start gap-3">
          <p className="text-sm text-muted-foreground">{t("hosting.notHost", { server, folder: known.folder })}</p>
          {operator && (
            <Button size="sm" disabled={enable.isPending} onClick={() => enable.mutate(undefined)}>
              {t("hosting.enable")}
            </Button>
          )}
          {enable.error && <Alert tone="danger">{errorMessage(enable.error)}</Alert>}
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="lg:col-span-2">
        {title}
        <CardContent>
          <Alert tone="danger">{errorMessage(error)}</Alert>
        </CardContent>
      </Card>
    );
  }
  if (isPending || !host) {
    return <Skeleton className="h-40 lg:col-span-2" />;
  }

  const added = host.sites.filter((s) => !s.main).length;
  const full = added >= host.max_sites;
  return (
    // Above the next cards: the page's entry animation makes each card a stacking context,
    // and the last site's menu runs over the card below.
    <ServerName.Provider value={server}>
      <Card className="relative z-10 lg:col-span-2">
        {title}
        <CardContent className="grid gap-3">
          {host.upgrade_required && <Alert tone="warn">{t("hosting.upgradeRequired", { server })}</Alert>}
          {host.stopped && !host.upgrade_required && <Alert tone="info">{t("hosting.stopped", { server })}</Alert>}
          <ConfigStatus appId={appId} host={host} always={advanced} onJob={onJob} />
          <ul className="divide-y" aria-label={name ?? t("hosting.title")}>
            {host.sites.map((site) => (
              <HostedSiteRow key={site.id} appId={appId} site={site} locked={host.upgrade_required} stopped={host.stopped} onJob={onJob} />
            ))}
          </ul>
          {operator && (
            <div className="flex flex-wrap items-center gap-3">
              <AddSiteDialog appId={appId} disabled={host.upgrade_required || host.stopped || full} />
              {full && <span className="text-xs text-muted-foreground">{t("hosting.full", { n: host.max_sites, server })}</span>}
            </div>
          )}
        </CardContent>
      </Card>
    </ServerName.Provider>
  );
}
