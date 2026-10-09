"use client";

import { useQuery } from "@tanstack/react-query";

import { Alert } from "@/components/ui/alert";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Connection = {
  ip: string;
  origin: "lan" | "internet";
  connections: number;
  first_seen: number; // seconds since the epoch
  targets: { port: number; name: string }[];
};
type Connections = { conntrack: boolean; connections: Connection[] };

const th = "px-2 py-1 text-left font-medium text-muted-foreground";

/** Who is connected to the host right now, one row per remote address, read every 3 s
 *  (the Internet first). Read only: blocking an app's visitors is not UFW's job (Docker
 *  bypasses it). */
export function LiveConnections() {
  const { t, lang } = useI18n();
  const { data, error } = useQuery({
    queryKey: ["host-firewall", "connections"],
    queryFn: () => api<Connections>("/host-firewall/connections"),
    refetchInterval: 3000,
  });
  const since = (at: number) => {
    const s = Math.max(0, Math.round(Date.now() / 1000 - at));
    const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    return s < 60 ? rtf.format(-s, "second") : s < 3600 ? rtf.format(-Math.round(s / 60), "minute") : rtf.format(-Math.round(s / 3600), "hour");
  };
  return (
    <section className="surface grid gap-2 rounded-lg border p-3" aria-label={t("fw.connections")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{t("fw.connections")}</h3>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span aria-hidden className="size-2 animate-pulse rounded-full bg-ok" /> {t("fw.connectionsLive")}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{t("fw.connectionsHelp")}</p>
      {data && !data.conntrack && <Alert tone="warn">{t("fw.conntrackMissing")}</Alert>}
      {error && <Alert tone="danger">{String(error)}</Alert>}
      {data && data.connections.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("fw.noConnections")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className={th}>{t("fw.address")}</th>
                <th className={th}>{t("fw.reaches")}</th>
                <th className={cn(th, "text-right")}>{t("fw.connectionCount")}</th>
                <th className={th}>{t("fw.since")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data?.connections.map((c) => (
                <tr key={c.ip}>
                  <td className="whitespace-nowrap px-2 py-1">
                    <span className="font-mono">{c.ip}</span>{" "}
                    <span className={cn("rounded px-1 text-[10px]", c.origin === "internet" ? "bg-danger/15 text-danger" : "bg-muted text-muted-foreground")}>
                      {t(c.origin === "internet" ? "fw.origin.internet" : "fw.origin.lan")}
                    </span>
                  </td>
                  <td className="px-2 py-1">
                    {c.targets.map((x) => (
                      <span key={x.port} className="mr-2 inline-block">
                        {x.name || "—"} <span className="font-mono text-muted-foreground">({x.port})</span>
                      </span>
                    ))}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{c.connections}</td>
                  <td className="whitespace-nowrap px-2 py-1 text-muted-foreground">{since(c.first_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
