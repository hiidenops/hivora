"use client";

import { useMutation } from "@tanstack/react-query";
import { Check, Download, FileJson, Hand, LayoutTemplate, ListChecks, Plus, SquareDashedMousePointer, Undo2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import type { Level } from "./layout";

const select = "h-9 rounded-md border bg-card px-2 text-sm";

/** The kind of a declared item (adding one, or in its inspector). */
export function KindSelect({ value, onChange }: { value: string; onChange: (kind: string) => void }) {
  const { t } = useI18n();
  return (
    <select className={select} value={value} onChange={(e) => onChange(e.target.value)} aria-label={t("topology.kind")}>
      {["firewall", "router", "vpn", "device", "note"].map((k) => (
        <option key={k} value={k}>
          {t(`topology.kind.${k}` as "topology.kind.note")}
        </option>
      ))}
    </select>
  );
}

/** Above the drawing: the detail level, adding a declared item, the prepared changes
 *  (list, apply, discard), the automatic layout, the exports. */
export function Toolbar({ level, tooBig, onLevel, mode, onMode, canEdit, pending, showPending, onTogglePending, applying, onApply, onDiscard, onPng, onJson, onRefresh }: {
  level: Level; // the one shown (zones only when the graph is too big)
  tooBig: boolean;
  onLevel: (level: Level) => void;
  mode: "pan" | "select"; // what dragging on the background does
  onMode: (mode: "pan" | "select") => void;
  canEdit: boolean;
  pending: number; // prepared changes
  showPending: boolean;
  onTogglePending: () => void;
  applying: boolean;
  onApply: () => void;
  onDiscard: () => void;
  onPng: () => void;
  onJson: () => void;
  onRefresh: () => void;
}) {
  const { t } = useI18n();
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState("firewall");
  const [label, setLabel] = useState("");
  const add = useMutation({
    mutationFn: () => api("/topology/nodes", { method: "POST", body: { kind, label } }),
    onSuccess: () => {
      setAdding(false);
      setLabel("");
      void onRefresh();
    },
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label={t("topology.level")} className="inline-flex rounded-md border p-0.5">
          {(["zones", "apps", "all"] as Level[]).map((l) => (
            <button
              key={l}
              role="tab"
              aria-selected={level === l}
              disabled={tooBig && l !== "zones"}
              onClick={() => onLevel(l)}
              className={cn("rounded px-3 py-1 text-sm transition-colors disabled:opacity-40", level === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
            >
              {t(`topology.level.${l}` as "topology.level.zones")}
            </button>
          ))}
        </div>
        <div role="tablist" aria-label={t("topology.drag")} className="inline-flex rounded-md border p-0.5">
          {(["pan", "select"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              title={t(`topology.drag.${m}Help` as "topology.drag.panHelp")}
              onClick={() => onMode(m)}
              className={cn("flex items-center gap-1.5 rounded px-3 py-1 text-sm transition-colors", mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
            >
              {m === "pan" ? <Hand className="size-4" /> : <SquareDashedMousePointer className="size-4" />}
              {t(`topology.drag.${m}` as "topology.drag.pan")}
            </button>
          ))}
        </div>
        {canEdit && (
          <Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)}>
            <Plus /> {t("topology.add")}
          </Button>
        )}
        <span className="ml-auto flex gap-1">
          {pending > 0 && (
            <span className="mr-2 flex gap-1 rounded-md border border-warn/60 bg-warn/10 p-0.5">
              <Button size="sm" variant="ghost" aria-expanded={showPending} title={t("topology.pending", { n: pending })} aria-label={t("topology.pending", { n: pending })} onClick={onTogglePending}>
                <ListChecks /> {pending}
              </Button>
              <Button size="sm" disabled={applying} title={t("topology.apply", { n: pending })} onClick={onApply}>
                <Check /> {applying ? t("common.loading") : t("topology.applyShort")}
              </Button>
              <Button size="sm" variant="ghost" title={t("topology.discard")} aria-label={t("topology.discard")} onClick={onDiscard}>
                <Undo2 />
              </Button>
            </span>
          )}
          {canEdit && (
            <Button size="sm" variant="ghost" title={t("topology.resetLayout")} aria-label={t("topology.resetLayout")} onClick={() => window.confirm(t("topology.resetConfirm")) && void api("/topology/layout", { method: "PUT", body: { positions: {} } }).then(onRefresh)}>
              <LayoutTemplate />
            </Button>
          )}
          <Button size="sm" variant="ghost" title={t("topology.png")} aria-label={t("topology.png")} onClick={onPng}>
            <Download />
          </Button>
          <Button size="sm" variant="ghost" title={t("topology.json")} aria-label={t("topology.json")} onClick={onJson}>
            <FileJson />
          </Button>
        </span>
      </div>
      {adding && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <KindSelect value={kind} onChange={setKind} />
          <Input className="h-9 w-64" required maxLength={120} placeholder={t("topology.labelPlaceholder")} value={label} onChange={(e) => setLabel(e.target.value)} aria-label={t("topology.label")} />
          <Button size="sm" type="submit" disabled={add.isPending}>
            {t("topology.addButton")}
          </Button>
          <p className="w-full text-xs text-muted-foreground">{t("topology.addHelp")}</p>
        </form>
      )}
    </>
  );
}
