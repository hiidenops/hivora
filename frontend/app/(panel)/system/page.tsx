"use client";

import dynamic from "next/dynamic";

import { PageHeader, useSession } from "@/components/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SourceLink } from "@/features/system/source-link";
import { useSystemInfo } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";

const StatusCard = dynamic(() => import("@/features/system/status-card").then((m) => m.StatusCard));
const ReleasesCard = dynamic(() => import("@/features/system/releases-card").then((m) => m.ReleasesCard));

/** The panel itself: its version and machine, its health, its updates (the last two for
 *  admins). Reached from the button at the bottom of the navigation, which carries the dot. */
export default function SystemPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: system } = useSystemInfo();
  return (
    <>
      <PageHeader title={t("nav.system")} />
      <div className="stagger grid items-start gap-4 xl:grid-cols-2">
        {can("admin") && <ReleasesCard />}
        {can("admin") && <StatusCard />}
        {system && (
          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle>{t("settings.system")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                {(
                  [
                    ["settings.system.version", system.version],
                    ["settings.system.docker", system.docker_version ?? "—"],
                    ["settings.system.arch", `${t(`arch.${system.arch}` as MessageKey)} (${system.arch})`],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-muted-foreground">{t(k)}</dt>
                    <dd className="font-mono">{v}</dd>
                  </div>
                ))}
              </dl>
              <SourceLink className="mt-4" />
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
