"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type HostSample } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { useLiveHost } from "@/lib/realtime";

const W = 600;
const H = 140;
export const WINDOW_S = 300; // live view: the last five minutes

interface Series {
  label: string;
  color: string; // CSS var of a validated chart colour
  values: number[];
}

function useHostHistory(): HostSample[] {
  const { data } = useQuery({
    queryKey: ["metrics", "host"],
    queryFn: () => api<HostSample[]>("/metrics/host"),
    staleTime: Infinity,
  });
  const live = useLiveHost();
  return useMemo(() => {
    const last = data?.at(-1)?.ts ?? 0;
    return [...(data ?? []), ...live.filter((s) => s.ts > last)].slice(-1800);
  }, [data, live]);
}

export function units(lang: string) {
  const num = (v: number, digits = 1) =>
    new Intl.NumberFormat(lang, { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
  const gb = (bytes: number) => `${num(bytes / 1024 ** 3)} ${lang === "fr" ? "Go" : "GB"}`;
  const rate = (bps: number) => {
    const [div, unit] =
      bps >= 1024 ** 2 ? [1024 ** 2, lang === "fr" ? "Mo/s" : "MB/s"] : [1024, lang === "fr" ? "Ko/s" : "KB/s"];
    return `${num(bps / div)} ${unit}`;
  };
  const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  const clock = (ts: number, seconds = false) =>
    new Date(ts * 1000).toLocaleTimeString(lang, {
      hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}),
    });  // prettier-ignore
  const size = (bytes: number) =>
    bytes >= 1024 ** 3 ? gb(bytes) : `${num(bytes / 1024 ** 2, 0)} ${lang === "fr" ? "Mo" : "MB"}`;
  return { num, gb, size, rate, time, clock };
}

/**
 * Server time "now", advancing smoothly between samples. Anchored on the last
 * sample (not the browser clock, which may be skewed) and ticked every frame so
 * the chart scrolls continuously; one step per sample with reduced motion.
 */
export function useScrollingNow(lastTs: number | undefined): number {
  const anchor = useRef({ ts: 0, at: 0 });
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (lastTs === undefined) return;
    anchor.current = { ts: lastTs, at: performance.now() };
    setNow(lastTs);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = 0;
    const loop = (t: number) => {
      if (t - last > 33) {
        last = t;
        setNow(anchor.current.ts + (t - anchor.current.at) / 1000);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [lastTs]);
  return now;
}

/** Scrolling time series: one y axis, recessive grid, crosshair + tooltip on hover. */
export function TimeChart({
  series,
  times,
  now,
  max,
  format,
  clock,
  area = false,
}: {
  series: Series[];
  times: number[];
  now: number;
  max: number;
  format: (v: number) => string;
  clock: (ts: number, seconds?: boolean) => string;
  area?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = times.length;
  const x = (i: number) => W - ((now - times[i]) / WINDOW_S) * W;
  const y = (v: number) => H - (Math.min(v, max) / (max || 1)) * (H - 8);
  const path = (values: number[]) => values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  // One tick per minute, scrolling with the data.
  const ticks: number[] = [];
  for (let t = Math.ceil((now - WINDOW_S) / 60) * 60; t <= now; t += 60) ticks.push(t);
  const xAt = (t: number) => W - ((now - t) / WINDOW_S) * W;

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const t = now - WINDOW_S * (1 - (e.clientX - box.left) / box.width);
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(times[i] - t) < Math.abs(times[best] - t)) best = i;
    setHover(n ? best : null);
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-36 w-full touch-none overflow-hidden"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        aria-hidden
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} className="stroke-grid" vectorEffect="non-scaling-stroke" />
        ))}
        {ticks.map((t) => (
          <line key={t} x1={xAt(t)} x2={xAt(t)} y1={0} y2={H} className="stroke-grid" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
        ))}
        {n > 0 &&
          series.map((s) => (
            <g key={s.label}>
              {area && <path d={`${path(s.values)} L${x(n - 1)},${H} L${x(0)},${H} Z`} fill={s.color} opacity={0.14} />}
              <path
                d={path(s.values)}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          ))}
        {hover !== null && hover < n && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={0}
            y2={H}
            className="stroke-muted-foreground"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      {hover !== null && hover < n && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border bg-card px-2 py-1 text-xs shadow-md"
          style={{
            left: `${Math.max(0, Math.min(100, (x(hover) / W) * 100))}%`,
            transform: `translateX(${x(hover) > W / 2 ? "-105%" : "5%"})`,
          }}
        >
          <div className="font-mono text-muted-foreground">{clock(times[hover], true)}</div>
          {series.map((s) => (
            <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="size-2 rounded-full" style={{ background: s.color }} />
              {series.length > 1 && <span className="text-muted-foreground">{s.label}</span>}
              <span className="font-mono">{format(s.values[hover])}</span>
            </div>
          ))}
        </div>
      )}
      <div className="relative mt-1 h-4 overflow-hidden text-[11px] text-muted-foreground" aria-hidden>
        {ticks.map((t) => (
          <span
            key={t}
            className="absolute top-0 -translate-x-1/2 font-mono tabular-nums"
            style={{ left: `${(xAt(t) / W) * 100}%` }}
          >
            {clock(t)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ChartCard({ title, value, children }: { title: string; value: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function HostCharts() {
  const { t, lang } = useI18n();
  const history = useHostHistory();
  const u = units(lang);
  const now = useScrollingNow(history.at(-1)?.ts);
  // Keep one sample beyond the left edge so the line enters from outside.
  const firstVisible = history.findIndex((s) => s.ts >= now - WINDOW_S);
  const samples = firstVisible < 0 ? history.slice(-1) : history.slice(Math.max(0, firstVisible - 1));
  const clock = u.clock;

  if (history.length === 0) {
    return (
      <div role="status" aria-label={t("common.loading")} className="grid gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-60" />
        ))}
      </div>
    );
  }
  const last = samples[samples.length - 1];
  const times = samples.map((s) => s.ts);
  const rx = samples.map((s) => s.net_rx_bps);
  const tx = samples.map((s) => s.net_tx_bps);
  const netMax = Math.max(1024, ...rx, ...tx) * 1.15;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard title={t("metrics.cpu")} value={`${u.num(last.cpu_percent)} %`}>
        <TimeChart
          area
          series={[{ label: t("metrics.cpu"), color: "var(--chart-1)", values: samples.map((s) => s.cpu_percent) }]}
          times={times}
          now={now}
          max={100}
          format={(v) => `${u.num(v)} %`}
          clock={clock}
        />
      </ChartCard>
      <ChartCard
        title={t("metrics.ram")}
        value={
          <>
            {u.gb(last.mem_used)} <span className="text-base font-normal text-muted-foreground">/ {u.gb(last.mem_total)}</span>
          </>
        }
      >
        <TimeChart
          area
          series={[{ label: t("metrics.ram"), color: "var(--chart-1)", values: samples.map((s) => s.mem_used) }]}
          times={times}
          now={now}
          max={last.mem_total}
          format={u.gb}
          clock={clock}
        />
      </ChartCard>
      <ChartCard
        title={t("metrics.network")}
        value={
          // Legend with direct values: identity never rests on colour alone.
          <span className="flex flex-wrap gap-x-4 text-base">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-[var(--chart-2)]" />
              {t("metrics.in")} <span className="font-semibold">{u.rate(last.net_rx_bps)}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-[var(--chart-1)]" />
              {t("metrics.out")} <span className="font-semibold">{u.rate(last.net_tx_bps)}</span>
            </span>
          </span>
        }
      >
        <TimeChart
          series={[
            { label: t("metrics.in"), color: "var(--chart-2)", values: rx },
            { label: t("metrics.out"), color: "var(--chart-1)", values: tx },
          ]}
          times={times}
          now={now}
          max={netMax}
          format={u.rate}
          clock={clock}
        />
      </ChartCard>
      <table className="sr-only">
        <caption>{t("metrics.title")}</caption>
        <thead>
          <tr>
            <th>{t("activity.when")}</th>
            <th>{t("metrics.cpu")}</th>
            <th>{t("metrics.ram")}</th>
            <th>{t("metrics.in")}</th>
            <th>{t("metrics.out")}</th>
          </tr>
        </thead>
        <tbody>
          {samples.slice(-10).map((s) => (
            <tr key={s.ts}>
              <td>{u.time(s.ts)}</td>
              <td>{u.num(s.cpu_percent)} %</td>
              <td>
                {u.gb(s.mem_used)} / {u.gb(s.mem_total)}
              </td>
              <td>{u.rate(s.net_rx_bps)}</td>
              <td>{u.rate(s.net_tx_bps)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
