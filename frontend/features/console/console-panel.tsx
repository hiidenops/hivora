"use client";

import { BookOpen, SquareTerminal, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { AppDetail } from "@/lib/api/client";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { useRealtime, type Message } from "@/lib/realtime";
import { cn } from "@/lib/utils";

import type { TerminalHandle } from "./terminal";

const XTerm = dynamic(() => import("./terminal"), {
  ssr: false,
  loading: () => <Skeleton className="size-full" />,
});

type Kind = "server" | "shell";
type Phase = "idle" | "totp" | "open" | "closed";
type Controller = ReturnType<ReturnType<typeof useRealtime>["openConsole"]>;

export function ConsolePanel({ app, running }: { app: AppDetail; running: boolean }) {
  const { t, l } = useI18n();
  const rt = useRealtime();
  const hasServer = app.console.server;
  const [kind, setKind] = useState<Kind>(hasServer ? "server" : "shell");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(true);
  const [session, setSession] = useState(0); // remounts the terminal per console
  const ctrl = useRef<Controller | null>(null);
  const term = useRef<TerminalHandle | null>(null);
  const size = useRef({ rows: 24, cols: 80 });
  const totp = useRef<string | undefined>(undefined);

  const onMessage = useCallback(
    (msg: Message) => {
      if (msg.type === "data") term.current?.write(String(msg.data));
      if (msg.type === "error") {
        ctrl.current = null;
        if (msg.code === "totp_required") return setPhase("totp");
        const key = `error.${msg.code}` as MessageKey;
        setError(t(key, { message: String(msg.message ?? msg.code) }));
        setPhase("closed");
      }
      if (msg.type === "closed") {
        ctrl.current = null;
        term.current?.write(`\r\n\x1b[2m${t(msg.reason === "idle" ? "console.idle" : "console.closed")}\x1b[0m\r\n`);
        setPhase("closed");
      }
    },
    [t],
  );

  const connect = useCallback(() => {
    ctrl.current?.close();
    setError(null);
    ctrl.current = rt.openConsole(
      { id: crypto.randomUUID(), app: app.id, kind, ...size.current, totp_code: totp.current },
      onMessage,
    );
    totp.current = undefined;
    setPhase("open");
  }, [rt, app.id, kind, onMessage]);

  const start = () => {
    setSession((n) => n + 1);
    setPhase("open");
  };
  const stop = () => {
    ctrl.current?.close();
    ctrl.current = null;
    setPhase("idle");
  };
  useEffect(() => () => ctrl.current?.close(), []);

  const submitTotp = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    totp.current = String(new FormData(e.currentTarget).get("code"));
    connect();
  };

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2">
          <SquareTerminal className="size-5" /> {t("console.title")}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" className="inline-flex rounded-md border p-0.5">
            {(hasServer ? (["server", "shell"] as Kind[]) : (["shell"] as Kind[])).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                disabled={phase === "open"}
                onClick={() => setKind(k)}
                className={cn(
                  "rounded px-3 py-1 text-sm transition-colors disabled:cursor-not-allowed",
                  kind === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                )}
              >
                {t(k === "server" ? "console.server" : "console.shell")}
              </button>
            ))}
          </div>
          {app.console.commands.length > 0 && kind === "server" && (
            <Button variant="outline" size="sm" aria-pressed={guideOpen} onClick={() => setGuideOpen((v) => !v)}>
              <BookOpen /> {t("console.guide")}
            </Button>
          )}
          {phase === "open" ? (
            <Button variant="outline" size="sm" onClick={stop}>
              <X /> {t("console.close")}
            </Button>
          ) : (
            <Button size="sm" disabled={!running} onClick={start}>
              {t("console.open")}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
        {!running && phase !== "open" && <Alert>{t("console.notRunning")}</Alert>}
        {kind === "shell" && <p className="text-xs text-muted-foreground">{t("console.shellHint")}</p>}
        {phase === "totp" && (
          <form onSubmit={submitTotp} className="flex flex-wrap items-end gap-2">
            <Alert tone="warn" className="w-full">
              {t("console.totp")}
            </Alert>
            <Input name="code" inputMode="numeric" autoComplete="one-time-code" className="w-40 font-mono" required autoFocus />
            <Button type="submit" size="sm">
              {t("settings.totp.verify")}
            </Button>
          </form>
        )}
        {error && <Alert tone="danger">{error}</Alert>}
        {(phase === "open" || phase === "closed") && session > 0 && (
          <div className="flex h-96 gap-3">
            <div className="min-w-0 flex-1">
              <XTerm
                key={session}
                onInput={(d) => ctrl.current?.input(d)}
                onResize={(rows, cols) => {
                  size.current = { rows, cols };
                  ctrl.current?.resize(rows, cols);
                }}
                onReady={(handle, initial) => {
                  term.current = handle;
                  size.current = initial;
                  connect();
                }}
              />
            </div>
            {guideOpen && kind === "server" && app.console.commands.length > 0 && (
              <aside className="animate-enter hidden w-64 shrink-0 overflow-y-auto rounded-md border md:block" aria-label={t("console.guide")}>
                <p className="border-b px-3 py-2 text-xs text-muted-foreground">{t("console.guideHint")}</p>
                <ul>
                  {app.console.commands.map((c) => (
                    <li key={c.command}>
                      <button
                        className="w-full px-3 py-2 text-left transition-colors hover:bg-muted"
                        onClick={() => {
                          ctrl.current?.input(c.command);
                          term.current?.focus();
                        }}
                      >
                        <code className="block font-mono text-xs">{c.command}</code>
                        <span className="text-xs text-muted-foreground">{l(c.description)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </aside>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
