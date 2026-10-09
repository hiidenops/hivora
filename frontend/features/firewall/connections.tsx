"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { api, type JobRef } from "@/lib/api/client";
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

export const useConnections = () =>
  useQuery({ queryKey: ["host-firewall", "connections"], queryFn: () => api<Connections>("/host-firewall/connections"), refetchInterval: 3000 });

/** Who is connected to the host right now, one row per remote address, read every 3 s
 *  (the Internet first). Read only: blocking an app's visitors is not UFW's job (Docker
 *  bypasses it). Without conntrack on the host, a button installs it (a job); `act` runs
 *  it as the page's other host changes (a fresh TOTP asked for when needed). */
export function LiveConnections({ act }: { act?: (f: () => Promise<unknown>) => void }) {
  const { t, lang } = useI18n();
  const track = useTrackJob();
  const install = () =>
    window.confirm(t("fw.conntrackConfirm")) &&
    act?.(async () => track((await api<JobRef>("/host-firewall/connections/conntrack", { method: "POST" })).id));
  const { data, error } = useConnections();
  const since = (at: number) => {
    const s = Math.max(0, Math.round(Date.now() / 1000 - at));
    const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto", style: "short" });
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
      {data && !data.conntrack && (
        <Alert tone="warn" className="flex flex-wrap items-center justify-between gap-3">
          <span>{t("fw.conntrackMissing")}</span>
          {act && (
            <Button size="sm" variant="outline" onClick={install}>
              <Download /> {t("fw.conntrackInstall")}
            </Button>
          )}
        </Alert>
      )}
      {error && <Alert tone="danger">{String(error)}</Alert>}
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.address")}</Th>
            <Th>{t("fw.reaches")}</Th>
            <Th numeric>{t("fw.connectionCount")}</Th>
            <Th>{t("fw.since")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.connections.length === 0 && <TEmpty colSpan={4}>{t("fw.noConnections")}</TEmpty>}
          {data?.connections.map((c) => (
            <Tr key={c.ip}>
              <Td className="whitespace-nowrap">
                <span className="font-mono text-xs">{c.ip}</span>
                <span
                  className={cn(
                    "ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                    c.origin === "internet" ? "bg-danger/10 text-danger" : "bg-muted text-muted-foreground",
                  )}
                >
                  <span aria-hidden className={cn("size-1.5 rounded-full", c.origin === "internet" ? "bg-danger" : "bg-ok")} />
                  {t(c.origin === "internet" ? "fw.origin.internet" : "fw.origin.lan")}
                </span>
              </Td>
              <Td>
                <span className="flex flex-wrap gap-1">
                  {c.targets.map((x) => (
                    <span key={x.port} className="rounded-md border bg-muted/40 px-1.5 py-0.5 text-xs">
                      {x.name || "—"} <span className="font-mono text-muted-foreground">:{x.port}</span>
                    </span>
                  ))}
                </span>
              </Td>
              <Td numeric>{c.connections}</Td>
              <Td className="whitespace-nowrap text-xs text-muted-foreground">{since(c.first_seen)}</Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </section>
  );
}
