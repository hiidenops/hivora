"use client";

import dynamic from "next/dynamic";

import { PageHeader } from "@/components/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n";

// React Flow is only loaded here (never on the other pages).
const TopologyView = dynamic(() => import("@/features/topology/topology-view").then((m) => m.TopologyView), {
  ssr: false,
  loading: () => <Skeleton className="h-[70vh]" />,
});

export default function TopologyPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("topology.title")} />
      <p className="-mt-4 mb-4 text-sm text-muted-foreground">{t("topology.description")}</p>
      <TopologyView />
    </>
  );
}
