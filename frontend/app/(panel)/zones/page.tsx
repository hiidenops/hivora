"use client";

import { Network, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { ZoneActions } from "@/features/zones/zone-actions";
import { ZoneDialog } from "@/features/zones/zone-dialog";
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
      <div className="stagger grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
        {zones?.map((z) => {
          const inside = (apps ?? []).filter((a) => a.zone_id === z.id);
          return (
            <article key={z.slug} aria-label={z.name} className="surface relative grid gap-4 overflow-hidden rounded-xl border p-5 pl-6">
              <span aria-hidden className="absolute inset-y-0 left-0 w-1.5" style={{ background: z.color }} />
              <div className="flex items-start justify-between gap-3">
                <div className="grid gap-1">
                  <h2 className="text-lg font-semibold">{z.name}</h2>
                  <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Network className="size-4" /> {t(`zones.mode.${z.network_mode === "shared" ? "shared" : "none"}`)}
                  </span>
                </div>
                {z.is_system && <Badge>{t("zones.system")}</Badge>}
              </div>
              {inside.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("zones.empty")}</p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {inside.map((a) => (
                    <li key={a.id}>
                      <Link href={`/app/?id=${a.id}`} className="flex items-center gap-2 rounded-md border bg-card px-2 py-1 text-sm hover:bg-muted">
                        <AppIcon src={a.icon_url} name={a.name} className="size-5 rounded" /> {a.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <ZoneActions zone={z} operator={operator} hasApps={inside.length > 0} />
              {operator && (
                <div className="flex gap-2">
                  <ZoneDialog zone={z} trigger={<Button variant="outline" size="sm"><Pencil /> {t("zones.edit")}</Button>} />
                  {!z.is_system && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={remove.isPending || z.apps > 0}
                      title={z.apps > 0 ? t("zones.notEmpty") : undefined}
                      onClick={() => window.confirm(t("zones.deleteConfirm", { name: z.name })) && remove.mutate(z.slug)}
                    >
                      <Trash2 className="text-danger" /> {t("action.remove")}
                    </Button>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </>
  );
}
