"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type PointerEvent } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type HostSample } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { useLiveHost } from "@/lib/realtime";

const W = 600;
const H = 140;

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
    return [...(data ?? []), ...live.filter((s) => s.ts > last)].slice(-360);
  }, [data, live]);
}

function units(lang: string) {
  const num = (v: number, digits = 1) =>
    new Intl.NumberFormat(lang, { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
  const gb = (bytes: number) => `${num(bytes / 1024 ** 3)} ${lang === "fr" ? "Go" : "GB"}`;
  const rate = (bps: number) => {
    const [div, unit] =
      bps >= 1024 ** 2 ? [1024 ** 2, lang === "fr" ? "Mo/s" : "MB/s"] : [1024, lang === "fr" ? "Ko/s" : "KB/s"];
    return `${num(bps / div)} ${unit}`;
  };
  const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  return { num, gb, rate, time };
}

/** Line/area time series: one y axis, recessive grid, crosshair + tooltip on hover. */
function TimeChart({
  series,
  times,
  max,
  format,
  timeLabel,
  area = false,
}: {
  series: Series[];
  times: number[];
  max: number;
  format: (v: number) => string;
  timeLabel: (ts: number) => string;
  area?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = times.length;
  const x = (i: number) => (n <= 1 ? W : (i / (n - 1)) * W);
  const y = (v: number) => H - (Math.min(v, max) / (max || 1)) * (H - 8);
  const path = (values: number[]) => values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - box.left) / box.width) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-36 w-full touch-none"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        aria-hidden
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} className="stroke-grid" vectorEffect="non-scaling-stroke" />
        ))}
        {series.map((s) => (
          <g key={s.label}>
            {area && (
              <path d={`${path(s.values)} L${x(n - 1)},${H} L${x(0)},${H} Z`} fill={s.color} opacity={0.14} />
            )}
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
        {hover !== null && (
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
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border bg-card px-2 py-1 text-xs shadow-md"
          style={{ left: `${(x(hover) / W) * 100}%`, transform: `translateX(${hover > n / 2 ? "-105%" : "5%"})` }}
        >
          <div className="text-muted-foreground">{timeLabel(times[hover])}</div>
          {series.map((s) => (
            <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="size-2 rounded-full" style={{ background: s.color }} />
              {series.length > 1 && <span className="text-muted-foreground">{s.label}</span>}
              <span className="font-mono">{format(s.values[hover])}</span>
            </div>
          ))}
        </div>
      )}
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
        <span>{n ? timeLabel(times[0]) : ""}</span>
        <span>{n ? timeLabel(times[n - 1]) : ""}</span>
      </div>
    </div>
  );
}

function ChartCard({ title, value, children }: { title: string; value: React.ReactNode; children: React.ReactNode }) {
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
  const samples = useHostHistory();
  const u = units(lang);

  if (samples.length === 0) {
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
          max={100}
          format={(v) => `${u.num(v)} %`}
          timeLabel={u.time}
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
          max={last.mem_total}
          format={u.gb}
          timeLabel={u.time}
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
          max={netMax}
          format={u.rate}
          timeLabel={u.time}
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
