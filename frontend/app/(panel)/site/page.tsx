"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useHostedSites } from "@/features/hosting/hooks";
import { useI18n } from "@/lib/i18n";

/** Older bookmarks (/site/?id={app}): the main site of that nginx, on its hosted site page;
 *  its app page if it hosts no sites. */
function OldSiteRedirect() {
  const { t } = useI18n();
  const router = useRouter();
  const id = Number(useSearchParams().get("id") ?? 0);
  const { data: host, error } = useHostedSites(id);
  const main = host?.sites.find((s) => s.main);

  useEffect(() => {
    if (main) router.replace(`/app/site/?app=${id}&site=${main.id}`);
    else if (host || error) router.replace(`/app/?id=${id}`);
  }, [main, host, error, id, router]);

  return <Skeleton role="status" aria-label={t("common.loading")} className="h-10 w-1/3" />;
}

export default function OldSitePage() {
  return (
    <Suspense>
      <OldSiteRedirect />
    </Suspense>
  );
}
