"use client";

import { Download, Eraser, ScrollText } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { CollapsibleCard } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n";
import { useRealtime, type Message } from "@/lib/realtime";

type Line = { s: string; t: string | null; l: string; n: number };
const KEEP = 5000; // lines kept in the browser
const SHOW = 1500; // lines rendered (the newest matching ones)
const TINTS = ["text-info", "text-warn", "text-ok", "text-primary", "text-danger"];

/** Live logs of every container of the app; streamed only while the card is open. */
export function LogsCard({ appId }: { appId: number }) {
  const { t, lang } = useI18n();
  const rt = useRealtime();
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [service, setService] = useState("");
  const [search, setSearch] = useState("");
  const [follow, setFollow] = useState(true);
  const [dropped, setDropped] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const counter = useRef(0);
  const onToggle = useCallback((o: boolean) => setOpen(o), []);

  useEffect(() => {
    if (!open) return;
    return rt.openLogs(appId, (msg: Message) => {
      if (msg.type === "opened") {
        setLines([]); // (re)connected: the server sends the recent lines again
        setServices(msg.services as string[]);
        setError(null);
      } else if (msg.type === "lines") {
        const batch = (msg.lines as Omit<Line, "n">[]).map((l) => ({ ...l, n: counter.current++ }));
        setLines((prev) => [...prev, ...batch].slice(-KEEP));
        setServices((prev) => {
          const more = batch.map((l) => l.s).filter((s) => !prev.includes(s));
          return more.length ? [...new Set([...prev, ...more])].sort() : prev;
        });
        if (msg.dropped) setDropped((d) => d + (msg.dropped as number));
      } else if (msg.type === "error") {
        setError(String(msg.code));
      }
    });
  }, [open, appId, rt]);

  const needle = search.trim().toLowerCase();
  const shown = useMemo(
    () => lines.filter((l) => (!service || l.s === service) && (!needle || l.l.toLowerCase().includes(needle))).slice(-SHOW),
    [lines, service, needle],
  );
  useLayoutEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown, follow]);

  const tint = (s: string) => TINTS[Math.max(0, services.indexOf(s)) % TINTS.length];
  const time = (ts: string | null) => (ts ? new Date(ts).toLocaleTimeString(lang) : "");
  const download = `/api/v1/apps/${appId}/logs${service ? `?service=${encodeURIComponent(service)}` : ""}`;

  return (
    <CollapsibleCard
      storageKey="app.logs"
      className="lg:col-span-2"
      onToggle={onToggle}
      title={
        <>
          <ScrollText className="size-5" /> {t("logs.title")}
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label={t("logs.service")} className="h-9 rounded-md border bg-card px-2 text-sm" value={service} onChange={(e) => setService(e.target.value)}>
            <option value="">{t("logs.allServices")}</option>
            {services.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <Input type="search" aria-label={t("logs.search")} placeholder={t("logs.search")} className="h-9 w-48" value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={follow} onChange={(e) => setFollow(e.target.checked)} /> {t("logs.follow")}
          </label>
          <span className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => setLines([])} title={t("logs.clear")} aria-label={t("logs.clear")}>
              <Eraser />
            </Button>
            <Button size="sm" variant="ghost" asChild>
              <a href={download} download title={t("logs.download")} aria-label={t("logs.download")}>
                <Download />
              </a>
            </Button>
          </span>
        </div>
        {error && <p className="text-sm text-danger">{t("logs.error", { code: error })}</p>}
        {dropped > 0 && <p className="text-xs text-muted-foreground">{t("logs.dropped", { n: dropped })}</p>}
        <div
          ref={box}
          role="log"
          aria-live="off"
          onWheel={() => follow && box.current && box.current.scrollTop + box.current.clientHeight < box.current.scrollHeight - 40 && setFollow(false)}
          className="min-h-64 flex-1 overflow-auto rounded-md bg-[#1c1917] p-3 font-mono text-xs leading-5 text-stone-200"
        >
          {shown.length === 0 ? (
            <p className="text-stone-400">{lines.length ? t("logs.noMatch") : t("logs.empty")}</p>
          ) : (
            shown.map((l) => (
              <div key={l.n} className="whitespace-pre-wrap break-all">
                <span className="select-none text-stone-500">{time(l.t)} </span>
                {services.length > 1 && <span className={`select-none ${tint(l.s)}`}>{l.s} </span>}
                {l.l}
              </div>
            ))
          )}
        </div>
      </div>
    </CollapsibleCard>
  );
}
