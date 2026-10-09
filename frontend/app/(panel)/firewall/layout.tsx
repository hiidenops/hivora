"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { FIREWALL_TABS, PageHeader } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { FirewallProvider, HostStatus, useHost } from "@/features/firewall/host";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** The firewall's pages: one header, their tabs, one TOTP prompt; past the overview, each
 *  needs the host agent. */
export default function FirewallLayout({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <FirewallProvider>
      <PageHeader title={t("nav.firewall")} />
      <nav aria-label={t("fw.sections")} className="-mt-2 mb-5 flex gap-1 overflow-x-auto border-b">
        {FIREWALL_TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={pathname === tab.href ? "page" : undefined}
            className={cn(
              "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
              pathname === tab.href ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <tab.icon className="size-4" /> {t(tab.label)}
          </Link>
        ))}
      </nav>
      <div className="grid gap-4 text-sm">
        <HostStatus />
        {pathname === "/firewall/" ? children : <NeedsAgent>{children}</NeedsAgent>}
      </div>
    </FirewallProvider>
  );
}

function NeedsAgent({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { state } = useHost();
  if (!state.data) return null;
  if (state.data.agent) return children;
  return (
    <Alert tone="info">
      {t("fw.agentOff")}{" "}
      <Link href="/firewall/" className="font-medium underline">
        {t("fw.tab.overview")}
      </Link>
    </Alert>
  );
}
