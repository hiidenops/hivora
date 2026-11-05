"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pencil, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { useTrackJob } from "@/components/job-toasts";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TileSkeletons } from "@/components/ui/skeleton";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { ChangeDialog } from "@/features/addressing/change-dialog";
import { api, type AddressChange, type AddressRow, type AddressingPlan } from "@/lib/api/client";
import { useAddressing } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type ZonePlan = AddressingPlan["zones"][number];

const STATE: Record<string, string> = { ok: "bg-ok/10 text-ok", drift: "bg-warn/10 text-warn", pending: "bg-muted text-muted-foreground" };
const box = "surface grid gap-3 rounded-xl border p-5";

/** "host:lan", "docker:bridge", "vpn:maison"...: what holds an excluded network, in words. */
function useOwner() {
  const { t } = useI18n();
  return (owner: string) => {
    const [kind, name = ""] = owner.split(/:(.*)/s);
    if (owner === "host:lan") return t("addr.owner.lan");
    if (owner === "zone:administration") return t("addr.owner.admin");
    if (kind === "host") return t("addr.owner.route", { name });
    if (kind === "docker") return t("addr.owner.docker", { name });
    if (kind === "vpn") return t("addr.owner.vpn", { name });
    return owner;
  };
}

/** The addressing plan: the Hivora range, what is kept out of it, each zone's subnet and
 *  every container's fixed address, next to the one Docker really gave (the gap shown).
 *  Changes (advanced mode): a zone's subnet, an address, the range; "Apply the plan". */
export default function AddressingPage() {
  const { t } = useI18n();
  const { can, advanced } = useSession();
  const { data, isPending } = useAddressing();
  const owner = useOwner();
  const edit = advanced && can("operator");

  return (
    <>
      <PageHeader title={t("addr.title")} actions={edit && <ApplyPlan />} />
      <p className="mb-6 max-w-3xl text-sm text-muted-foreground">{t("addr.intro")}</p>
      {isPending && <TileSkeletons label={t("common.loading")} count={3} />}
      {data && (
        <div className="stagger grid gap-4">
          <section className={box} aria-label={t("addr.range")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold">{t("addr.range")}</h2>
              {advanced && can("admin") && (
                <ChangeDialog
                  trigger={<Button variant="outline" size="sm"><Pencil /> {t("addr.changeRange")}</Button>}
                  title={t("addr.changeRange")}
                  help={t("addr.rangeHelp")}
                  label={t("addr.range")}
                  initial={data.range}
                  placeholder="10.100.0.0/16"
                  path="/addressing/range"
                  body={(v) => ({ range: v ?? "" })}
                />
              )}
            </div>
            <p className="font-mono text-2xl font-semibold">{data.range}</p>
            <dl className="grid gap-1 text-sm sm:grid-cols-2">
              <div><dt className="text-muted-foreground">{t("addr.zonesBlock")}</dt><dd className="font-mono">{data.zones_block}</dd></div>
              <div><dt className="text-muted-foreground">{t("addr.appsBlock")}</dt><dd className="font-mono">{data.apps_block}</dd></div>
            </dl>
            <div className="grid gap-1.5">
              <h3 className="text-sm font-medium">{t("addr.excluded")}</h3>
              <p className="text-xs text-muted-foreground">{t("addr.excludedHelp")}</p>
              <ul className="flex flex-wrap gap-2">
                {data.excluded.map((e) => (
                  <li key={`${e.network}-${e.owner}`} className="rounded-md border bg-card px-2 py-1 text-xs">
                    <span className="font-mono">{e.network}</span> <span className="text-muted-foreground">· {owner(e.owner)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>
          {data.zones.map((z) => (
            <ZoneCard key={z.slug} zone={z} edit={edit} />
          ))}
          <section className={box} aria-label={t("addr.appNetworks")}>
            <h2 className="font-semibold">{t("addr.appNetworks")}</h2>
            <p className="text-xs text-muted-foreground">{t("addr.appNetworksHelp", { block: data.apps_block })}</p>
            <Rows rows={data.app_networks} edit={edit} subnet />
          </section>
        </div>
      )}
    </>
  );
}

const ORIGIN: Record<string, MessageKey> = {
  range: "addr.origin.range",
  vpn: "addr.origin.vpn",
  manual: "addr.origin.manual",
  system: "addr.origin.system",
};

function ZoneCard({ zone: z, edit }: { zone: ZonePlan; edit: boolean }) {
  const { t } = useI18n();
  // Docker's network on another subnet: applied by the zone's next redeploy.
  const gap = !!z.network && z.actual_subnets.length > 0 && !!z.subnet && !z.actual_subnets.includes(z.subnet);
  const pieces = Object.fromEntries(z.app_networks.map((n) => [n.app, n.subnet]));
  return (
    <article aria-label={z.name} className="surface relative grid gap-3 overflow-hidden rounded-xl border p-5 pl-6">
      <span aria-hidden className="absolute inset-y-0 left-0 w-1.5" style={{ background: z.color }} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
          {z.name}
          <span className="font-mono text-base font-medium text-muted-foreground">{z.subnet ?? "—"}</span>
          <Badge>{t(ORIGIN[z.origin] ?? "addr.origin.range", { vpn: z.vpn ?? "" })}</Badge>
        </h2>
        {edit && z.origin !== "system" && (
          <ChangeDialog
            trigger={<Button variant="outline" size="sm"><Pencil /> {t("addr.changeSubnet")}</Button>}
            title={t("addr.changeSubnetOf", { zone: z.name })}
            help={t(z.network ? "addr.subnetHelp" : "addr.subnetHelpPieces")}
            label={t("addr.subnet")}
            initial={z.origin === "manual" ? (z.subnet ?? "") : ""}
            placeholder={z.subnet ?? "10.100.1.0/24"}
            path={`/addressing/zones/${z.slug}`}
            body={(v) => ({ subnet: v })}
            automatic
          />
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {t(z.network ? "addr.mode.shared" : "addr.mode.pieces")} · {t("addr.used", { used: z.used, size: z.size })}
      </p>
      {gap && <Alert tone="warn">{t("addr.subnetGap", { actual: z.actual_subnets.join(", ") })}</Alert>}
      <Rows rows={z.rows.map((r) => ({ ...r, subnet: pieces[r.app] }))} edit={edit} subnet={!z.network} />
    </article>
  );
}

function Rows({ rows, edit, subnet = false }: { rows: (AddressRow & { subnet?: string })[]; edit: boolean; subnet?: boolean }) {
  const { t } = useI18n();
  return (
    <Table>
      <THead>
        <tr>
          <Th>{t("addr.col.app")}</Th>
          <Th>{t("addr.col.service")}</Th>
          {subnet && <Th>{t("addr.col.network")}</Th>}
          <Th>{t("addr.col.planned")}</Th>
          <Th>{t("addr.col.actual")}</Th>
          <Th>{t("addr.col.state")}</Th>
          {edit && <Th>{t("fw.action")}</Th>}
        </tr>
      </THead>
      <TBody>
        {rows.length === 0 && <TEmpty colSpan={6 + (subnet ? 1 : 0) + (edit ? 1 : 0)}>{t("addr.noRow")}</TEmpty>}
        {rows.map((r) => (
          <Tr key={`${r.network}-${r.app}-${r.service}`}>
            <Td>{r.app_id ? <Link className="hover:underline" href={`/app/?id=${r.app_id}`}>{r.name}</Link> : r.name}</Td>
            <Td mono>{r.service}</Td>
            {subnet && <Td mono>{r.subnet ?? "—"}</Td>}
            <Td mono>
              {r.planned}
              {r.manual && <span className="ml-1.5 text-[10px] text-muted-foreground">{t("addr.manual")}</span>}
            </Td>
            <Td mono>{r.actual ?? "—"}</Td>
            <Td>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", STATE[r.state] ?? STATE.pending)}>{t(`addr.state.${r.state}` as MessageKey)}</span>
            </Td>
            {edit && (
              <Td>
                {r.app_id && (
                  <ChangeDialog
                    trigger={<Button variant="ghost" size="icon" aria-label={t("addr.changeIpOf", { app: r.name, service: r.service })} title={t("addr.changeIp")}><Pencil /></Button>}
                    title={t("addr.changeIpOf", { app: r.name, service: r.service })}
                    help={t("addr.ipHelp", { network: r.network })}
                    label={t("addr.col.planned")}
                    initial={r.manual ? r.planned : ""}
                    placeholder={r.planned}
                    path={`/addressing/apps/${r.app_id}/ip`}
                    body={(v) => ({ service: r.service, network: r.network, address: v })}
                    automatic
                  />
                )}
              </Td>
            )}
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

/** Redeploys the apps whose applied compose differs from the plan. */
function ApplyPlan() {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const track = useTrackJob();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = async () => {
    if (!window.confirm(t("addr.applyConfirm"))) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api<AddressChange>("/addressing/apply", { method: "POST" });
      const refresh = () => void qc.invalidateQueries({ queryKey: ["addressing"] });
      out.jobs?.forEach((j) => track(j.id, refresh));
      setResult(out.apps.length ? t("addr.applied", { apps: out.apps.join(", ") }) : t("addr.upToDate"));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-3">
      {!!error && <span className="text-sm text-danger">{errorMessage(error)}</span>}
      {result && <span className="text-sm text-muted-foreground">{result}</span>}
      <Button variant="outline" onClick={run} loading={busy} disabled={busy}>
        <RefreshCw /> {t("addr.applyPlan")}
      </Button>
    </div>
  );
}
