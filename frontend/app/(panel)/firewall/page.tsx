"use client";

import { Alert } from "@/components/ui/alert";
import { useBlocked } from "@/features/firewall/blocked";
import { LiveConnections } from "@/features/firewall/connections";
import { AgentSwitch, useHost } from "@/features/firewall/host";
import { Overview } from "@/features/firewall/overview";
import { useI18n } from "@/lib/i18n";

export default function FirewallPage() {
  const { t } = useI18n();
  const { state, act } = useHost();
  const { data: blocked } = useBlocked();
  return (
    <>
      {/* The agent's switch on the left, the Docker warning beside it. */}
      <div className="flex flex-wrap items-stretch gap-4">
        <AgentSwitch className="max-w-md" />
        <Alert tone="warn" className="flex min-w-72 flex-1 items-center">
          {t("fw.dockerBypass")}
        </Alert>
      </div>
      {/* The other sections at a glance (each tile opens its tab), then who is connected now. */}
      {state.data?.agent ? (
        <>
          <Overview />
          <LiveConnections act={act} blocked={blocked?.map((b) => b.address)} />
        </>
      ) : (
        <p className="max-w-4xl text-muted-foreground">{t("fw.help")}</p>
      )}
    </>
  );
}
