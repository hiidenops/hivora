"use client";

import { X } from "lucide-react";

import { useI18n } from "@/lib/i18n";

import { changeKey, type Change } from "./changes";

/** The prepared changes, listed: none applied yet; each can be dropped. */
export function PendingPanel({ changes, onRemove }: { changes: Change[]; onRemove: (c: Change) => void }) {
  const { t } = useI18n();
  return (
    <section aria-label={t("topology.pending", { n: changes.length })} className="surface absolute left-3 top-3 z-10 grid max-h-[60%] w-80 gap-2 overflow-auto rounded-lg border p-3 text-xs shadow-lg">
      <p className="font-medium">{t("topology.pending", { n: changes.length })}</p>
      <ul className="grid gap-1">
        {changes.map((c) => (
          <li key={changeKey(c)} className="flex items-center justify-between gap-2">
            <span>
              {c.kind === "move"
                ? t("topology.change.move", { app: c.app, zone: c.zoneLabel })
                : c.kind === "expose"
                  ? t("topology.change.expose", { app: c.app, port: c.port, exposure: c.exposure === "default" ? t("topology.exposure.reopen") : t(`topology.exposure.${c.exposure}` as "topology.exposure.lan") })
                  : t(c.on ? "topology.change.reach" : "topology.change.unreach", { vpn: c.vpn, target: c.targetLabel })}
            </span>
            <button className="text-muted-foreground hover:text-foreground" aria-label={t("overrides.remove")} onClick={() => onRemove(c)}>
              <X className="size-4" />
            </button>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground">{t("topology.pendingHelp")}</p>
    </section>
  );
}
