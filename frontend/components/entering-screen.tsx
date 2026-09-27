"use client";

import { Brand } from "@/components/brand";
import { useI18n } from "@/lib/i18n";

/** Short full-screen transition after signing in: the wordmark and a filling honey bar. */
export function EnteringScreen() {
  const { t } = useI18n();
  return (
    <div role="status" aria-label={t("login.entering")} className="entering fixed inset-0 z-50 grid place-items-center bg-background">
      <div className="grid w-48 justify-items-center gap-6">
        <Brand large />
        <span className="h-1 w-full overflow-hidden rounded-full bg-muted">
          <span className="entering-bar block h-full rounded-full bg-primary" />
        </span>
      </div>
    </div>
  );
}
