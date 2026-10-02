"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { CreateSiteDialog } from "@/features/sites/create-site-dialog";
import { useSites } from "@/features/sites/hooks";
import { JobsCard } from "@/features/sites/jobs-card";
import { SiteCard } from "@/features/sites/site-card";
import { useI18n } from "@/lib/i18n";

export default function SitesPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: sites, isPending } = useSites();
  const [jobs, setJobs] = useState<number[]>([]);
  const create = <CreateSiteDialog trigger={<Button><Plus /> {t("sites.create")}</Button>} onJobs={setJobs} />;

  return (
    <>
      <PageHeader title={t("sites.title")} actions={can("operator") && create} />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("sites.intro")}</p>
      <JobsCard jobs={jobs} className="animate-enter mb-6" />
      {isPending && <TileSkeletons label={t("common.loading")} count={2} />}
      {sites?.length === 0 && (
        <div className="surface grid justify-items-start gap-3 rounded-xl border p-6">
          <p className="text-muted-foreground">{t("sites.empty")}</p>
          {can("operator") && create}
        </div>
      )}
      <div className="stagger grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
        {sites?.map((s) => (
          <SiteCard key={s.id} site={s} onJob={(id) => setJobs([id])} />
        ))}
      </div>
    </>
  );
}
