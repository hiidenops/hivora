"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader, useSession } from "@/components/app-shell";
import { useTrackJob } from "@/components/job-toasts";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { HostedSitesCard } from "@/features/hosting/hosted-sites-card";
import { useApps } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** Every site, grouped by the nginx that hosts it: one Sites card per nginx app. */
export default function SitesPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: apps, isPending } = useApps();
  const follow = useTrackJob(); // in a pop-up
  const hosts = apps?.filter((a) => a.template === "nginx") ?? [];
  // One request per nginx that hosts sites (GET /apps/{id}/sites); none for the others.
  const deploy = (
    <Button asChild>
      <Link href="/deploy/?template=nginx">
        <Plus /> {t("sites.newHost")}
      </Link>
    </Button>
  );

  return (
    <>
      <PageHeader title={t("sites.title")} actions={can("operator") && deploy} />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("sites.intro")}</p>
      {isPending && <TileSkeletons label={t("common.loading")} count={2} />}
      {apps && hosts.length === 0 && (
        <div className="surface grid justify-items-start gap-3 rounded-xl border p-6">
          <p className="text-muted-foreground">{t("sites.empty")}</p>
          {can("operator") && deploy}
        </div>
      )}
      <div className="stagger grid gap-4">
        {hosts.map((a) => (
          <HostedSitesCard key={a.id} appId={a.id} hosting={a.hosting} title={a.name} onJob={(id) => follow(id)} />
        ))}
      </div>
    </>
  );
}
