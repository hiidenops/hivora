"use client";

import { AppWindow, CornerDownLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, type KeyboardEvent } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useApps } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { FIREWALL_TABS, NAV_GROUPS, NAV_HOME, useSession } from "./app-shell";

type Hit = { key: string; href: string; label: string; detail?: string; icon: typeof AppWindow };

// Accents and case ignored: "parefeu" finds "Pare-feu", "activite" finds "Activité".
const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/gi, "").toLowerCase();

/** Ctrl+K: go to an app or a page by typing a few letters. Only navigates: actions stay on
 *  their pages (and their jobs). */
export function CommandPalette({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const router = useRouter();
  const { can } = useSession();
  const { data: apps } = useApps();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const pages = useMemo<Hit[]>(() => {
    const items = [NAV_HOME, ...NAV_GROUPS.flatMap((g) => g.items)].filter((n) => can(n.role));
    // The firewall's tabs too (its overview is the Firewall entry itself).
    const subs = can("admin") ? FIREWALL_TABS.slice(1) : [];
    return [
      ...items.map((n) => ({ key: n.href, href: n.href, label: t(n.label), icon: n.icon })),
      ...subs.map((e) => ({ key: e.href, href: e.href, label: t(e.label), detail: t("nav.firewall"), icon: e.icon })),
    ];
  }, [can, t]);

  const q = fold(query);
  const appHits: Hit[] = (apps ?? [])
    .map((a) => ({ key: `app-${a.id}`, href: `/app/?id=${a.id}`, label: a.name, detail: a.slug, icon: AppWindow }))
    .filter((h) => !q || fold(h.label).includes(q) || fold(h.detail).includes(q));
  const pageHits = pages.filter((h) => !q || fold(h.label).includes(q) || fold(h.detail ?? "").includes(q));
  const sections = [
    { title: t("palette.apps"), hits: q ? appHits : appHits.slice(0, 8) },
    { title: t("palette.pages"), hits: pageHits },
  ].filter((s) => s.hits.length > 0);
  const flat = sections.flatMap((s) => s.hits);
  const selected = Math.min(index, Math.max(flat.length - 1, 0));

  const go = (hit: Hit | undefined) => {
    if (!hit) return;
    onClose();
    router.push(hit.href);
  };
  const keys = (e: KeyboardEvent) => {
    const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (step && flat.length) {
      e.preventDefault();
      setIndex((selected + step + flat.length) % flat.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(flat[selected]);
    }
  };

  let n = -1;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("palette.title")} closeLabel={t("common.close")} className="top-[15vh] max-w-xl translate-y-0 gap-3 p-4" aria-describedby={undefined}>
        <input
          autoFocus
          role="combobox"
          aria-expanded
          aria-controls="palette-list"
          aria-activedescendant={flat[selected] ? `palette-${flat[selected].key}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={keys}
          placeholder={t("palette.placeholder")}
          className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div id="palette-list" role="listbox" aria-label={t("palette.title")} className="grid max-h-[50vh] gap-3 overflow-y-auto">
          {sections.length === 0 && <p className="px-2 py-6 text-center text-sm text-muted-foreground">{t("palette.empty")}</p>}
          {sections.map((s) => (
            <div key={s.title} role="group" aria-label={s.title} className="grid gap-0.5">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{s.title}</p>
              {s.hits.map((h) => {
                const i = ++n;
                const on = i === selected;
                return (
                  <div
                    key={h.key}
                    id={`palette-${h.key}`}
                    role="option"
                    aria-selected={on}
                    onMouseMove={() => setIndex(i)}
                    onClick={() => go(h)}
                    className={cn("flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm", on && "bg-muted")}
                  >
                    <h.icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate">{h.label}</span>
                    {h.detail && <span className="truncate font-mono text-xs text-muted-foreground">{h.detail}</span>}
                    {on && <CornerDownLeft className="ml-auto size-3.5 shrink-0 text-muted-foreground" />}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
