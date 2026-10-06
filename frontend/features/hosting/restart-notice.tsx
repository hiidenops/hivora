"use client";

import { useSession } from "@/components/app-shell";
import { DiffView } from "@/components/diff-view";
import { Alert } from "@/components/ui/alert";
import type { SitePlan } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

/** Shown before any change that recreates the nginx container (a port is published or
 *  withdrawn): every site of this nginx stops a moment. The compose diff in advanced mode. */
export function RestartNotice({ plan }: { plan: SitePlan }) {
  const { t } = useI18n();
  const { advanced } = useSession();
  if (!plan.recreate) return null;
  return (
    <div className="grid gap-2">
      <Alert tone="warn">{t("hosting.restartNotice")}</Alert>
      {advanced && plan.diff && <DiffView diff={plan.diff} />}
    </div>
  );
}
