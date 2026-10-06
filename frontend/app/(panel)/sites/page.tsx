"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { HostedSitesCard } from "@/features/hosting/hosted-sites-card";
import { JobsCard } from "@/features/sites/jobs-card";
import { useApps } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** Every site, grouped by the nginx that hosts it: one Sites card per nginx app. */
export default function SitesPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: apps, isPending } = useApps();
  const [jobs, setJobs] = useState<number[]>([]);
  const hosts = apps?.filter((a) => a.template === "nginx") ?? [];
  // ponytail: one request per nginx (GET /apps/{id}/sites), fine for a homelab's few nginx.
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
      <JobsCard jobs={jobs} className="animate-enter mb-6" />
      {isPending && <TileSkeletons label={t("common.loading")} count={2} />}
      {apps && hosts.length === 0 && (
        <div className="surface grid justify-items-start gap-3 rounded-xl border p-6">
          <p className="text-muted-foreground">{t("sites.empty")}</p>
          {can("operator") && deploy}
        </div>
      )}
      <div className="stagger grid gap-4">
        {hosts.map((a) => (
          <HostedSitesCard key={a.id} appId={a.id} title={a.name} onJob={(id) => setJobs([id])} />
        ))}
      </div>
    </>
  );
}
