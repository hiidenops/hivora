"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Switch } from "@/components/ui/input";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { KEY, box, useHost } from "./host";

export type Listening = {
  protocol: string;
  address: string;
  port: number;
  process: string;
  app: string | null;
  ufw: "bypassed" | "off" | "local" | "allowed" | "blocked";
};
const TONE: Record<Listening["ufw"], string> = {
  bypassed: "border-danger/40 bg-danger/10 text-danger",
  off: "border-warn/40 bg-warn/10 text-warn",
  allowed: "border-warn/40 bg-warn/10 text-warn",
  local: "text-muted-foreground",
  blocked: "border-ok/40 bg-ok/10 text-ok",
};
export const reachable = (p: Listening) => p.ufw !== "local" && p.ufw !== "blocked";
export const useListening = () =>
  useQuery({
    queryKey: [...KEY, "listening"],
    queryFn: () => api<Listening[]>("/host-firewall/listening"),
    refetchInterval: 5000,
  });

export type Rule = {
  action: string;
  port: string;
  protocol: string;
  source: string;
};
export const NEW: Rule = {
  action: "allow",
  port: "",
  protocol: "tcp",
  source: "any",
};
const select = "h-9 rounded-md border bg-card px-2 text-sm";

/** The Ports page: what listens now (live), the UFW rules, and a rule's dialog that both open. */
export function PortsSection() {
  const { state } = useHost();
  const [draft, setDraft] = useState<Rule | null>(null);
  const ufw = !!state.data?.ufw_installed;
  return (
    <div className="grid gap-4">
      <ListeningPorts
        onPick={
          ufw
            ? (action, port, protocol) =>
                setDraft({
                  action,
                  port: String(port),
                  protocol,
                  source: "any",
                })
            : undefined
        }
      />
      <UfwRules onNew={() => setDraft(NEW)} />
      <RuleDialog draft={draft} onClose={() => setDraft(null)} />
    </div>
  );
}

/** What listens on the host right now, and whether it is reachable from outside. */
function ListeningPorts({ onPick }: { onPick?: (action: string, port: number, protocol: string) => void }) {
  const { t } = useI18n();
  const { data, error } = useListening();
  const [all, setAll] = useState(true);
  const shown = all ? data : data?.filter(reachable);
  return (
    <section className={box} aria-label={t("fw.openPorts")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{t("fw.openPorts")}</h3>
        <div className="flex rounded-md border p-0.5 text-xs" role="group">
          {([true, false] as const).map((v) => (
            <button
              key={String(v)}
              type="button"
              aria-pressed={all === v}
              onClick={() => setAll(v)}
              className={cn("rounded px-2 py-1", all === v ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground")}
            >
              {t(v ? "fw.filter.all" : "fw.filter.reachable")}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{t("fw.openPortsHelp")}</p>
      {!!error && <Alert tone="danger">{String(error)}</Alert>}
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.port")}</Th>
            <Th>{t("fw.address")}</Th>
            <Th>{t("fw.process")}</Th>
            <Th>{t("fw.reach")}</Th>
            {onPick && <Th />}
          </tr>
        </THead>
        <TBody>
          {shown?.length === 0 && <TEmpty colSpan={onPick ? 5 : 4}>{t("fw.noOpenPort")}</TEmpty>}
          {shown?.map((p) => (
            <Tr key={`${p.protocol}${p.address}${p.port}`}>
              <Td mono>
                {p.port}/{p.protocol}
              </Td>
              <Td mono>{p.address}</Td>
              <Td>{p.app ? t("fw.dockerApp", { app: p.app }) : p.process || "—"}</Td>
              <Td>
                <Badge className={cn("whitespace-nowrap", TONE[p.ufw])}>{t(`fw.reach.${p.ufw}`)}</Badge>
              </Td>
              {onPick && (
                <Td className="whitespace-nowrap py-1 text-right">
                  {p.ufw !== "local" && (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={p.ufw === "bypassed"}
                        title={p.ufw === "bypassed" ? t("fw.pickBypassed") : undefined}
                        onClick={() => onPick("allow", p.port, p.protocol)}
                      >
                        {t("fw.allow")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={p.ufw === "bypassed"}
                        title={p.ufw === "bypassed" ? t("fw.pickBypassed") : undefined}
                        onClick={() => onPick("deny", p.port, p.protocol)}
                      >
                        {t("fw.deny")}
                      </Button>
                    </>
                  )}
                </Td>
              )}
            </Tr>
          ))}
        </TBody>
      </Table>
    </section>
  );
}

/** UFW: its switch, its default policy and its rules (each deletable). `onNew`: opens a rule. */
export function UfwRules({ onNew }: { onNew: () => void }) {
  const { t } = useI18n();
  const { state, act } = useHost();
  const [keepSsh, setKeepSsh] = useState(true);
  const data = state.data;
  if (!data) return null;
  return (
    <section className={box} aria-label={t("fw.ufwRules")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{t("fw.ufwRules")}</h3>
        {data.ufw_installed && (
          <Button size="sm" onClick={onNew}>
            <Plus /> {t("fw.newRule")}
          </Button>
        )}
      </div>
      {!data.ufw_installed ? (
        <p className="text-muted-foreground">{t("fw.ufwMissing")}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Switch
              checked={data.ufw_active}
              onChange={(e) => {
                const enabled = e.target.checked;
                if (window.confirm(t(enabled ? "fw.enableConfirm" : "fw.disableConfirm")))
                  act(() =>
                    api("/host-firewall/ufw", {
                      method: "PUT",
                      body: { enabled, keep_ssh: keepSsh },
                    }),
                  );
              }}
              aria-label={t("fw.ufwActive")}
            />
            <span>{data.ufw_active ? t("fw.active") : t("fw.inactive")}</span>
            {data.ufw_defaults && <span className="text-xs text-muted-foreground">{data.ufw_defaults}</span>}
            {!data.ufw_active && (
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={keepSsh} onChange={(e) => setKeepSsh(e.target.checked)} /> {t("fw.keepSsh")}
              </label>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{t("fw.ufwRulesHelp")}</p>
          <Table>
            <THead>
              <tr>
                <Th numeric>#</Th>
                <Th>{t("fw.to")}</Th>
                <Th>{t("fw.action")}</Th>
                <Th>{t("fw.from")}</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {data.ufw_rules.length === 0 && <TEmpty colSpan={5}>{t("fw.noRule")}</TEmpty>}
              {data.ufw_rules.map((r) => (
                <Tr key={r.number}>
                  <Td numeric className="text-muted-foreground">
                    {r.number}
                  </Td>
                  <Td mono>{r.to}</Td>
                  <Td mono>{r.action}</Td>
                  <Td mono>{r.source}</Td>
                  <Td className="py-1 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("fw.deleteRule", { n: r.number })}
                      onClick={() =>
                        window.confirm(t("fw.deleteRule", { n: r.number })) &&
                        act(() =>
                          api(`/host-firewall/ufw/rules/${r.number}`, {
                            method: "DELETE",
                          }),
                        )
                      }
                    >
                      <Trash2 className="text-danger" />
                    </Button>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </>
      )}
    </section>
  );
}

/** A new UFW rule: blank, or filled from a listening port (the source left to choose). */
export function RuleDialog({ draft, onClose }: { draft: Rule | null; onClose: () => void }) {
  const { t } = useI18n();
  const { act, pending } = useHost();
  const [edit, setEdit] = useState<Rule | null>(null);
  const rule = edit ?? draft ?? NEW;
  const set = (k: keyof Rule, v: string) => setEdit({ ...rule, [k]: v });
  const close = () => {
    setEdit(null);
    onClose();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    act(() =>
      api("/host-firewall/ufw/rules", {
        method: "POST",
        body: { ...rule, port: Number(rule.port) },
      }),
    );
    close();
  };
  return (
    <Dialog open={!!draft} onOpenChange={(o) => !o && close()}>
      <DialogContent title={t("fw.newRule")} description={t("fw.ufwRulesHelp")} closeLabel={t("common.close")} className="max-w-lg">
        <form className="grid gap-3 text-sm" onSubmit={submit}>
          <label className="grid gap-1">
            {t("fw.action")}
            <select className={select} value={rule.action} onChange={(e) => set("action", e.target.value)}>
              <option value="allow">{t("fw.allow")}</option>
              <option value="limit">{t("fw.limit")}</option>
              <option value="deny">{t("fw.deny")}</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1">
              {t("fw.port")}
              <Input className="h-9" type="number" min={1} max={65535} required value={rule.port} onChange={(e) => set("port", e.target.value)} />
            </label>
            <label className="grid gap-1">
              {t("fw.protocol")}
              <select className={select} value={rule.protocol} onChange={(e) => set("protocol", e.target.value)}>
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
                <option value="any">TCP + UDP</option>
              </select>
            </label>
          </div>
          <label className="grid gap-1">
            {t("fw.source")}
            <Input className="h-9 font-mono text-xs" autoFocus={!!draft?.port} value={rule.source} onChange={(e) => set("source", e.target.value)} />
          </label>
          <div className="flex justify-end">
            <Button type="submit" disabled={pending}>
              {t("fw.addRule")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
