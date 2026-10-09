"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useI18n } from "@/lib/i18n";

import { Jails } from "./fail2ban";
import { AgentSwitch, FirewallProvider, HostStatus, useHost } from "./host";
import { NEW, RuleDialog, UfwRules, type Rule } from "./ports";

/** The host firewall dialog of the topology: the agent, UFW and fail2ban; the rest on the
 *  Firewall page. */
export function FirewallDialog({ open, onOpenChange, onChanged }: { open: boolean; onOpenChange: (o: boolean) => void; onChanged: () => void }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("fw.title")} description={t("fw.help")} closeLabel={t("common.close")} className="max-w-3xl">
        <div className="max-h-[70vh] overflow-auto">
          <FirewallProvider onChanged={onChanged}>
            <Compact />
          </FirewallProvider>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Compact() {
  const { t } = useI18n();
  const { state } = useHost();
  const [draft, setDraft] = useState<Rule | null>(null);
  return (
    <div className="grid gap-4 text-sm">
      <AgentSwitch />
      <Alert tone="warn">{t("fw.dockerBypass")}</Alert>
      <HostStatus />
      {state.data?.agent && (
        <>
          <UfwRules onNew={() => setDraft(NEW)} />
          <RuleDialog draft={draft} onClose={() => setDraft(null)} />
          <Jails />
        </>
      )}
      <Link href="/firewall/" className="flex items-center gap-1 justify-self-end text-primary hover:underline">
        {t("fw.openPage")} <ArrowRight className="size-4" />
      </Link>
    </div>
  );
}
