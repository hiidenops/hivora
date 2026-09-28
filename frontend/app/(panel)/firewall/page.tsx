"use client";

import { PageHeader } from "@/components/app-shell";
import { FirewallPanel } from "@/features/firewall/firewall-panel";
import { useI18n } from "@/lib/i18n";

export default function FirewallPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("nav.firewall")} />
      <div className="grid max-w-4xl gap-4">
        <p className="text-sm text-muted-foreground">{t("fw.help")}</p>
        <FirewallPanel full />
      </div>
    </>
  );
}
