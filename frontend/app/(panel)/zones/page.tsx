"use client";

import { Network, Pencil, Plus, Trash2 } from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";
import Link from "next/link";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { StartOrderButton, ZoneActionButtons, useZoneActions } from "@/features/zones/zone-actions";
import { ZoneDialog } from "@/features/zones/zone-dialog";
import type { App, Zone } from "@/lib/api/client";
import { useApps, useDeleteZone, useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

export default function ZonesPage() {
  const { t, errorMessage } = useI18n();
  const { can } = useSession();
  const { data: zones, isPending } = useZones();
  const { data: apps } = useApps();
  const remove = useDeleteZone();
  const operator = can("operator");

  return (
    <>
      <PageHeader
        title={t("zones.title")}
        actions={
          operator && (
            <ZoneDialog trigger={<Button><Plus /> {t("zones.create")}</Button>} />
          )
        }
      />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("zones.intro")}</p>
      {remove.error && <Alert tone="danger" className="mb-4">{errorMessage(remove.error)}</Alert>}
      {isPending && <TileSkeletons label={t("common.loading")} count={3} />}
      <div className="stagger grid grid-cols-[repeat(auto-fill,minmax(min(100%,30rem),1fr))] gap-4">
        {zones?.map((z) => (
          <ZoneCard key={z.slug} zone={z} apps={(apps ?? []).filter((a) => a.zone_id === z.id)} operator={operator} remove={remove} />
        ))}
      </div>
    </>
  );
}

const DOT: Record<string, string> = { healthy: "bg-ok", starting: "bg-info", degraded: "bg-warn", stopped: "bg-idle", error: "bg-danger" };

/** A zone: its name and network, its actions (start, stop, restart in its order) on the
 *  right; its apps with their state; then its start order, edit and remove. */
function ZoneCard({ zone: z, apps, operator, remove }: { zone: Zone; apps: App[]; operator: boolean; remove: UseMutationResult<unknown, Error, string> }) {
  const { t, errorMessage } = useI18n();
  const { run, error } = useZoneActions(z);
  return (
    <article aria-label={z.name} className="surface relative flex flex-col gap-4 overflow-hidden rounded-xl border p-5 pl-6">
      <span aria-hidden className="absolute inset-y-0 left-0 w-1.5" style={{ background: z.color }} />
      <div className="grid gap-1">
        {/* The name and the actions on one line (the details under them): room for both. */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            {z.name} {z.is_system && <Badge>{t("zones.system")}</Badge>}
          </h2>
          {operator && apps.length > 0 && <ZoneActionButtons zone={z} run={run} />}
        </div>
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Network className="size-4" /> {t(`zones.mode.${z.network_mode === "shared" ? "shared" : "none"}`)}
          <span aria-hidden>·</span> {t("zones.appCount", { n: apps.length })}
        </span>
      </div>
      {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {apps.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("zones.empty")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {apps.map((a) => (
            <li key={a.id}>
              <Link href={`/app/?id=${a.id}`} className="flex items-center gap-2 rounded-md border bg-card px-2 py-1 text-sm hover:bg-muted" title={t(`status.${a.status}`)}>
                <AppIcon src={a.icon_url} name={a.name} className="size-5 rounded" /> {a.name}
                <span aria-hidden className={`size-2 rounded-full ${DOT[a.status] ?? "bg-idle"}`} />
              </Link>
            </li>
          ))}
        </ul>
      )}
      <div className="-mx-5 -mb-5 -ml-6 mt-auto flex min-h-12 flex-wrap items-center justify-between gap-2 border-t bg-muted/30 px-5 py-2 pl-6">
        {apps.length > 0 ? <StartOrderButton zone={z} steps /> : <span />}
        {operator && (
          <div className="flex items-center gap-1">
            <ZoneDialog zone={z} trigger={<Button variant="ghost" size="icon" aria-label={t("zones.edit")} title={t("zones.edit")}><Pencil /></Button>} />
            {!z.is_system && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("action.remove")}
                disabled={remove.isPending || z.apps > 0}
                title={z.apps > 0 ? t("zones.notEmpty") : t("action.remove")}
                onClick={() => window.confirm(t("zones.deleteConfirm", { name: z.name })) && remove.mutate(z.slug)}
              >
                <Trash2 className="text-danger" />
              </Button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
