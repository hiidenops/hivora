"use client";

import { ChartCard, TimeChart, WINDOW_S, units, useScrollingNow } from "@/features/activity/host-charts";
import { useI18n } from "@/lib/i18n";
import { useAppMetrics } from "@/lib/realtime";

/** Live CPU, memory and network of one app, sampled while this card is shown. */
export function AppUsage({ slug }: { slug: string }) {
  const { t, lang } = useI18n();
  const u = units(lang);
  const history = useAppMetrics(slug, true);
  const now = useScrollingNow(history.at(-1)?.ts);
  const firstVisible = history.findIndex((s) => s.ts >= now - WINDOW_S);
  const samples = firstVisible < 0 ? history.slice(-1) : history.slice(Math.max(0, firstVisible - 1));
  const last = samples.at(-1);
  const times = samples.map((s) => s.ts);
  const cpu = samples.map((s) => s.cpu_percent);
  const mem = samples.map((s) => s.mem_bytes);
  const rx = samples.map((s) => s.net_rx_bps);
  const tx = samples.map((s) => s.net_tx_bps);
  // An app rarely uses the whole machine: scale to its own peak so the line reads.
  const mb = (bytes: number) => `${u.num(bytes / 1024 ** 2, 0)} ${lang === "fr" ? "Mo" : "MB"}`;
  const size = (bytes: number) => (bytes >= 1024 ** 3 ? u.gb(bytes) : mb(bytes));

  return (
    <section className="grid gap-3 lg:col-span-2" aria-label={t("usage.title")}>
      <h2 className="flex items-baseline gap-2 font-semibold">
        {t("usage.title")}
        {!last && <span className="text-sm font-normal text-muted-foreground">{t("usage.waiting")}</span>}
      </h2>
      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title={t("metrics.cpu")} value={last ? `${u.num(last.cpu_percent)} %` : "–"}>
          <TimeChart
            area
            series={[{ label: t("metrics.cpu"), color: "var(--chart-1)", values: cpu }]}
            times={times}
            now={now}
            max={Math.min(100, Math.max(5, ...cpu) * 1.25)}
            format={(v) => `${u.num(v)} %`}
            clock={u.clock}
          />
        </ChartCard>
        <ChartCard
          title={t("metrics.ram")}
          value={
            last ? (
              <>
                {size(last.mem_bytes)}{" "}
                <span className="text-base font-normal text-muted-foreground">/ {size(last.mem_limit)}</span>
              </>
            ) : (
              "–"
            )
          }
        >
          <TimeChart
            area
            series={[{ label: t("metrics.ram"), color: "var(--chart-1)", values: mem }]}
            times={times}
            now={now}
            max={Math.max(64 * 1024 ** 2, ...mem) * 1.25}
            format={size}
            clock={u.clock}
          />
        </ChartCard>
        <ChartCard
          title={t("metrics.network")}
          value={
            <span className="flex flex-wrap gap-x-4 text-base">
              <span className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-[var(--chart-2)]" />
                {t("metrics.in")} <span className="font-semibold">{last ? u.rate(last.net_rx_bps) : "–"}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-[var(--chart-1)]" />
                {t("metrics.out")} <span className="font-semibold">{last ? u.rate(last.net_tx_bps) : "–"}</span>
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
            max={Math.max(1024, ...rx, ...tx) * 1.15}
            format={u.rate}
            clock={u.clock}
          />
        </ChartCard>
      </div>
    </section>
  );
}
