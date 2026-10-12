"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useId, useState } from "react";

import { useTrackJob } from "@/components/job-toasts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { api, type JobRef } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { KEY, box, useHost } from "./host";
import { useRoutes } from "./routes";

type StaticRoute = {
  id: number;
  destination: string;
  gateway: string;
  dev: string | null;
  metric: number | null;
  note: string | null;
  applied: boolean | null; // set on the host now; null: unknown (agent off)
};

export const useStaticRoutes = () =>
  useQuery({ queryKey: [...KEY, "static-routes"], queryFn: () => api<StaticRoute[]>("/host-firewall/static-routes") });

const EMPTY = { destination: "", gateway: "", dev: "", metric: "", note: "" };
const field = "h-8 w-full min-w-24 text-xs";

/** The static IPv4 routes Hivora keeps on the host (proto 241): each with its state on the
 *  host, removable; a form to add one. Each change is a job followed in a pop-up. */
export function StaticRoutes() {
  const { t } = useI18n();
  const { act } = useHost();
  const qc = useQueryClient();
  const trackJob = useTrackJob();
  // At the job's end, the routes' state on the host (and the host's table) read again.
  const track = (id: number) => trackJob(id, () => void qc.invalidateQueries({ queryKey: KEY }));
  const { data } = useStaticRoutes();
  const { data: table } = useRoutes();
  const [form, setForm] = useState(EMPTY);
  const formId = useId(); // the add row's fields belong to this form (a form cannot wrap a row)
  const set = (key: keyof typeof EMPTY, value: string) => setForm({ ...form, [key]: value });
  const devs = [...new Set(table?.routes.map((r) => r.dev).filter(Boolean))].sort();

  const add = () => {
    const dst = form.destination.trim();
    const gw = form.gateway.trim();
    if (!window.confirm(t("fw.addRouteConfirm", { dst, gw }))) return;
    act(async () => {
      const body = { destination: dst, gateway: gw, dev: form.dev || null, metric: form.metric === "" ? null : Number(form.metric), note: form.note.trim() || null };
      const job = await api<JobRef>("/host-firewall/static-routes", { method: "POST", body });
      setForm(EMPTY); // accepted: a refusal keeps what was typed
      track(job.id);
    });
  };
  const remove = (r: StaticRoute) =>
    window.confirm(t("fw.removeRouteConfirm", { dst: r.destination, gw: r.gateway })) &&
    act(async () => track((await api<JobRef>(`/host-firewall/static-routes/${r.id}`, { method: "DELETE" })).id));

  return (
    <section className={box} aria-label={t("fw.staticRoutes")}>
      <h3 className="font-semibold">{t("fw.staticRoutes")}</h3>
      <p className="text-xs text-muted-foreground">{t("fw.staticRoutesHelp")}</p>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.route.dst")}</Th>
            <Th>{t("fw.route.gateway")}</Th>
            <Th>{t("fw.route.dev")}</Th>
            <Th numeric>{t("fw.route.metric")}</Th>
            <Th>{t("fw.note")}</Th>
            <Th>{t("fw.route.state")}</Th>
            <Th>{t("fw.action")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.length === 0 && <TEmpty colSpan={7}>{t("fw.noStaticRoute")}</TEmpty>}
          {data?.map((r) => (
            <Tr key={r.id}>
              <Td mono>{r.destination}</Td>
              <Td mono>{r.gateway}</Td>
              <Td mono>{r.dev ?? t("fw.route.auto")}</Td>
              <Td numeric mono>
                {r.metric ?? "—"}
              </Td>
              <Td className="text-xs">{r.note ?? "—"}</Td>
              <Td>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-medium",
                    r.applied === null ? "bg-muted text-muted-foreground" : r.applied ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn",
                  )}
                >
                  {t(r.applied === null ? "fw.route.unknown" : r.applied ? "fw.route.applied" : "fw.route.missing")}
                </span>
              </Td>
              <Td>
                <Button size="sm" variant="ghost" onClick={() => remove(r)} aria-label={t("fw.removeRoute", { dst: r.destination })} title={t("fw.removeRoute", { dst: r.destination })}>
                  <Trash2 />
                </Button>
              </Td>
            </Tr>
          ))}
          {/* The add row: each field under its column. */}
          <Tr>
            <Td>
              <Input form={formId} className={cn(field, "font-mono")} required placeholder="10.8.0.0/24" value={form.destination} onChange={(e) => set("destination", e.target.value)} aria-label={t("fw.route.dst")} />
            </Td>
            <Td>
              <Input form={formId} className={cn(field, "font-mono")} required placeholder="192.168.1.254" value={form.gateway} onChange={(e) => set("gateway", e.target.value)} aria-label={t("fw.route.gateway")} />
            </Td>
            <Td>
              <select form={formId} className={cn(field, "rounded-md border bg-card px-2 font-mono")} value={form.dev} onChange={(e) => set("dev", e.target.value)} aria-label={t("fw.route.dev")}>
                <option value="">{t("fw.route.auto")}</option>
                {devs.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </Td>
            <Td numeric>
              <Input form={formId} className={cn(field, "text-right font-mono")} type="number" min={0} placeholder="—" value={form.metric} onChange={(e) => set("metric", e.target.value)} aria-label={t("fw.route.metric")} />
            </Td>
            <Td>
              <Input form={formId} className={field} maxLength={200} placeholder={t("fw.note")} value={form.note} onChange={(e) => set("note", e.target.value)} aria-label={t("fw.note")} />
            </Td>
            <Td />
            <Td>
              <Button form={formId} size="sm" variant="outline" type="submit" aria-label={t("fw.addRoute")} title={t("fw.addRoute")}>
                <Plus />
              </Button>
            </Td>
          </Tr>
        </TBody>
      </Table>
      <form
        id={formId}
        aria-label={t("fw.addRoute")}
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      />
    </section>
  );
}
