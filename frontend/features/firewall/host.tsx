"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export type State = {
  agent: boolean;
  ufw_installed: boolean;
  ufw_active: boolean;
  ufw_defaults: string;
  ufw_rules: { number: number; to: string; action: string; source: string }[];
  fail2ban_installed: boolean;
  fail2ban_running: boolean;
  jails: {
    name: string;
    banned: string[];
    total_banned: number;
    failed: number;
  }[];
};
export const KEY = ["host-firewall"];
export const box = "surface grid gap-2 rounded-lg border p-3";

type Host = {
  state: UseQueryResult<State>;
  /** Runs a host change: a fresh TOTP asked for first when the server wants one. */
  act: (f: () => Promise<unknown>) => void;
  pending: boolean;
  error: unknown;
  totp: boolean;
  confirm: (code: string) => void;
  confirming: boolean;
};
const HostContext = createContext<Host | null>(null);

export function useHost(): Host {
  const ctx = useContext(HostContext);
  if (!ctx) throw new Error("useHost outside FirewallProvider");
  return ctx;
}

/** The host's firewall state and its changes, shared by the firewall's pages (one TOTP
 *  prompt, one error line, whichever page asked). `onChanged`: after each change. */
export function FirewallProvider({ onChanged, children }: { onChanged?: () => void; children: ReactNode }) {
  const qc = useQueryClient();
  const state = useQuery({
    queryKey: KEY,
    queryFn: () => api<State>("/host-firewall?fresh=true"),
  });
  const [retry, setRetry] = useState<null | (() => Promise<unknown>)>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: KEY });
    onChanged?.();
  };
  const act = useMutation({
    mutationFn: async (f: () => Promise<unknown>) => {
      try {
        return await f();
      } catch (e) {
        if (e instanceof ApiError && e.code === "totp_required") {
          setRetry(() => f);
          return null;
        }
        throw e;
      }
    },
    onSuccess: refresh,
  });
  const confirm = useMutation({
    mutationFn: async (code: string) => {
      await api("/host-firewall/confirm", { method: "POST", body: { code } });
      const f = retry;
      setRetry(null);
      if (f) await f();
    },
    onSuccess: refresh,
  });
  const host: Host = {
    state,
    act: (f) => act.mutate(f),
    pending: act.isPending,
    error: state.error ?? act.error ?? confirm.error,
    totp: !!retry,
    confirm: (code) => confirm.mutate(code),
    confirming: confirm.isPending,
  };
  return <HostContext.Provider value={host}>{children}</HostContext.Provider>;
}

/** The last error and, when asked for, the TOTP prompt. */
export function HostStatus() {
  const { t, errorMessage } = useI18n();
  const { error, totp, confirm, confirming } = useHost();
  const [code, setCode] = useState("");
  return (
    <>
      {!!error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {totp && (
        <form
          className="surface flex flex-wrap items-end gap-2 rounded-md border p-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            confirm(code);
            setCode("");
          }}
        >
          <p className="w-full">{t("fw.totp")}</p>
          <Input className="w-40 font-mono" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
          <Button type="submit" size="sm" disabled={confirming}>
            {t("settings.totp.verify")}
          </Button>
        </form>
      )}
    </>
  );
}

/** The host agent's switch (confirmed before turning it on). */
export function AgentSwitch({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state, act, pending } = useHost();
  return (
    <div className={cn("surface grid content-center gap-1 rounded-lg border p-3 text-sm", className)}>
      <label className="flex items-center gap-2 font-medium">
        <Switch
          checked={!!state.data?.agent}
          disabled={!state.data || pending}
          onChange={(e) => {
            const enabled = e.target.checked;
            if (!enabled || window.confirm(t("fw.agentConfirm")))
              act(() =>
                api("/host-firewall/agent", {
                  method: "PUT",
                  body: { enabled },
                }),
              );
          }}
        />
        {t("fw.agent")}
      </label>
      <p className="text-xs text-muted-foreground">{t("fw.agentHelp")}</p>
    </div>
  );
}
