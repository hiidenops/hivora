"use client";

import { useSession } from "@/components/app-shell";
import { DiffView } from "@/components/diff-view";
import { Alert } from "@/components/ui/alert";
import type { SitePlan } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { useServerName } from "./server";

/** Shown before any change that recreates the nginx container (a port is published or
 *  withdrawn): every site of this nginx stops a moment. The compose diff in advanced mode. */
export function RestartNotice({ plan, removal = false }: { plan: SitePlan; removal?: boolean }) {
  const { t } = useI18n();
  const server = useServerName();
  const { advanced } = useSession();
  if (!plan.recreate) return null;
  return (
    <div className="grid gap-2">
      <Alert tone="warn">{t(removal ? "hosting.restartNoticeRemove" : "hosting.restartNotice", { server })}</Alert>
      {advanced && plan.diff && <DiffView diff={plan.diff} />}
    </div>
  );
}
