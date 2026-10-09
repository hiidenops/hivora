"use client";

import { Alert } from "@/components/ui/alert";
import { AgentSwitch, useHost } from "@/features/firewall/host";
import { Overview } from "@/features/firewall/overview";
import { useI18n } from "@/lib/i18n";

export default function FirewallPage() {
  const { t } = useI18n();
  const { state } = useHost();
  return (
    <>
      {/* The agent's switch on the left, the Docker warning beside it. */}
      <div className="flex flex-wrap items-stretch gap-4">
        <AgentSwitch className="max-w-md" />
        <Alert tone="warn" className="flex min-w-72 flex-1 items-center">
          {t("fw.dockerBypass")}
        </Alert>
      </div>
      {state.data?.agent ? <Overview /> : <p className="max-w-4xl text-muted-foreground">{t("fw.help")}</p>}
    </>
  );
}
