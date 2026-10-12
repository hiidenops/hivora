"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldBan, Undo2 } from "lucide-react";
import { useState } from "react";

import { useTrackJob } from "@/components/job-toasts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { api, type JobRef } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { KEY, box, useHost } from "./host";

type Blocked = { address: string; note: string | null; created_by: number | null; created_at: string };

export const useBlocked = () => useQuery({ queryKey: [...KEY, "blocked"], queryFn: () => api<Blocked[]>("/host-firewall/blocked") });

// ponytail: the local ranges as the backend's hostfw.connections.LOCAL, only to word the
// confirmation (the backend decides nothing from it).
const LAN = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|169\.254\.|f[cd]|fe[89ab])/i;

/** Block (confirmed: stronger words for a local address) and unblock, each a job followed
 *  in a pop-up; `act` runs them as the firewall's other host changes (a fresh TOTP). */
export function useBlockActions(act?: (f: () => Promise<unknown>) => void) {
  const { t } = useI18n();
  const track = useTrackJob();
  /** `onDone`: once the server accepted it (a refusal keeps what was typed). */
  const block = (ip: string, note?: string, { lan = LAN.test(ip), onDone }: { lan?: boolean; onDone?: () => void } = {}) =>
    window.confirm(t(lan ? "fw.blockConfirmLan" : "fw.blockConfirm", { ip })) &&
    act?.(async () => {
      const job = await api<JobRef>("/host-firewall/blocked", { method: "POST", body: { address: ip, note: note || null } });
      onDone?.();
      track(job.id);
    });
  const unblock = (ip: string) =>
    act?.(async () => track((await api<JobRef>(`/host-firewall/blocked/${encodeURIComponent(ip)}`, { method: "DELETE" })).id));
  return { block, unblock };
}

/** The blocked addresses: what they cut, the list (unblock), and an address to block. */
export function BlockedAddresses() {
  const { t, lang } = useI18n();
  const { act } = useHost();
  const { data } = useBlocked();
  const { block, unblock } = useBlockActions(act);
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const date = new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" });
  return (
    <section className={box} aria-label={t("fw.blocked")}>
      <h3 className="font-semibold">{t("fw.blocked")}</h3>
      <p className="text-xs text-muted-foreground">{t("fw.blockedHelp")}</p>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.address")}</Th>
            <Th>{t("fw.note")}</Th>
            <Th>{t("fw.blockedAt")}</Th>
            <Th>{t("fw.action")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.length === 0 && <TEmpty colSpan={4}>{t("fw.noBlocked")}</TEmpty>}
          {data?.map((b) => (
            <Tr key={b.address}>
              <Td className="font-mono text-xs">{b.address}</Td>
              <Td className="text-xs">{b.note ?? "—"}</Td>
              <Td className="whitespace-nowrap text-xs text-muted-foreground">{date.format(new Date(b.created_at))}</Td>
              <Td>
                <Button size="sm" variant="ghost" onClick={() => unblock(b.address)} aria-label={t("fw.unblockIp", { ip: b.address })}>
                  <Undo2 /> {t("fw.unblock")}
                </Button>
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
      <form
        className="flex flex-wrap items-end gap-2"
        aria-label={t("fw.blockAddress")}
        onSubmit={(e) => {
          e.preventDefault();
          block(address.trim(), note.trim(), {
            onDone: () => {
              setAddress("");
              setNote("");
            },
          });
        }}
      >
        <Input
          className="h-8 w-52 font-mono text-xs"
          required
          placeholder="203.0.113.5"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          aria-label={t("fw.addressToBlock")}
        />
        <Input
          className="h-8 w-52 text-xs"
          maxLength={200}
          placeholder={t("fw.notePlaceholder")}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          aria-label={t("fw.note")}
        />
        <Button size="sm" variant="outline" type="submit">
          <ShieldBan /> {t("fw.blockAddress")}
        </Button>
      </form>
    </section>
  );
}
