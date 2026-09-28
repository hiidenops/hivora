"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { AppIcon } from "@/components/app-icon";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TileSkeletons } from "@/components/ui/skeleton";
import { AppActions } from "@/features/apps/app-actions";
import type { App, Zone } from "@/lib/api/client";
import { useApps, useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveStatus } from "@/lib/realtime";

function AppTile({ app }: { app: App }) {
  const status = useLiveStatus(app.slug, app.status);
  return (
    <Card className="card-interactive flex flex-col gap-3 p-4">
      <Link href={`/app/?id=${app.id}`} className="flex items-center gap-3">
        <AppIcon src={app.icon_url} name={app.name} />
        <span className="min-w-0">
          <span className="block truncate font-medium">{app.name}</span>
          <span className="block truncate font-mono text-xs text-muted-foreground">{app.slug}</span>
        </span>
      </Link>
      <div className="flex items-center justify-between">
        <StatusBadge status={status} drift={app.drift} />
        <AppActions id={app.id} status={status} compact />
      </div>
    </Card>
  );
}

const AdoptBanner = dynamic(() => import("@/features/apps/adopt-banner").then((m) => m.AdoptBanner));

export default function DashboardPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: apps, isPending } = useApps();
  const { data: zones } = useZones();
  const [query, setQuery] = useState("");

  const sections = useMemo(() => {
    const q = query.trim().toLowerCase();
    const visible = (apps ?? []).filter((a) => !q || a.name.toLowerCase().includes(q) || a.slug.includes(q));
    const groups: { zone: Zone | null; apps: App[] }[] = (zones ?? []).map((zone) => ({
      zone,
      apps: visible.filter((a) => a.zone_id === zone.id),
    }));
    groups.push({ zone: null, apps: visible.filter((a) => !zones?.some((z) => z.id === a.zone_id)) });
    return groups.filter((g) => g.apps.length > 0);
  }, [apps, zones, query]);

  return (
    <>
      <PageHeader
        title={t("dashboard.title")}
        actions={
          <Input
            className="w-64"
            placeholder={t("dashboard.search")}
            aria-label={t("dashboard.search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        }
      />
      {can("operator") && <AdoptBanner />}
      {isPending && <TileSkeletons label={t("common.loading")} />}
      {apps?.length === 0 && (
        <Card className="grid place-items-center gap-4 p-12 text-center">
          <p className="text-muted-foreground">{t("dashboard.empty")}</p>
          <Button asChild>
            <Link href="/catalog/">{t("dashboard.emptyCta")}</Link>
          </Button>
        </Card>
      )}
      <div className="grid gap-8">
        {sections.map(({ zone, apps: list }) => (
          <section key={zone?.id ?? "none"}>
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              <span className="size-2.5 rounded-full" style={{ background: zone?.color ?? "var(--idle)" }} />
              {zone?.name ?? t("dashboard.unclassified")}
            </h2>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
              {list.map((app, i) => (
                <div key={app.id} className="animate-enter" style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
                  <AppTile app={app} />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
