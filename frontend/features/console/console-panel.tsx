"use client";

import { BookOpen, CornerDownLeft, RotateCw, SquareTerminal } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/collapsible-card";
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

// Console ids only need to be unique per socket. (crypto.randomUUID is not an
// option: browsers only expose it on HTTPS or localhost, and Hivora is often
// reached over plain HTTP by LAN IP.)
let consoleSeq = 0;

type Kind = "server" | "shell";
type Phase = "connecting" | "totp" | "open" | "closed";
type Controller = ReturnType<ReturnType<typeof useRealtime>["openConsole"]>;

/** Console of a running app, in a foldable card: connects while unfolded, reconnects on demand. */
export function ConsolePanel({ app, running }: { app: AppDetail; running: boolean }) {
  const { t, l } = useI18n();
  const rt = useRealtime();
  const hasServer = app.console.server;
  const commands = app.console.commands;
  const [kind, setKind] = useState<Kind>(hasServer ? "server" : "shell");
  const [phase, setPhase] = useState<Phase>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(true);
  const [command, setCommand] = useState("");
  const history = useRef<string[]>([]);
  const back = useRef(0); // steps back in the history (arrow up), 0: the line being typed
  const line = useRef<HTMLInputElement>(null);
  const [session, setSession] = useState(0); // a new terminal (and console) per session
  const ctrl = useRef<Controller | null>(null);
  const term = useRef<TerminalHandle | null>(null);
  const size = useRef({ rows: 24, cols: 80 });
  const totp = useRef<string | undefined>(undefined);

  const onMessage = useCallback(
    (msg: Message) => {
      if (msg.type === "opened") setPhase("open");
      if (msg.type === "data") term.current?.write(String(msg.data));
      if (msg.type === "error") {
        ctrl.current = null;
        if (msg.code === "totp_required") return setPhase("totp");
        setError(t(`error.${msg.code}` as MessageKey, { message: String(msg.message ?? msg.code) }));
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

  const connect = useCallback(
    (as: Kind) => {
      ctrl.current?.close();
      setError(null);
      setPhase("connecting");
      ctrl.current = rt.openConsole(
        { id: `c${++consoleSeq}`, app: app.id, kind: as, ...size.current, totp_code: totp.current },
        onMessage,
      );
      totp.current = undefined;
    },
    [rt, app.id, onMessage],
  );

  const disconnect = () => {
    ctrl.current?.close();
    ctrl.current = null;
  };

  // A fresh terminal (and console) whenever the app runs, the kind changes or on reconnect.
  const restart = () => setSession((n) => n + 1);
  // Connected only while the card is unfolded.
  const [open, setOpen] = useState(false);
  const onToggle = useCallback((o: boolean) => setOpen(o), []);
  useEffect(() => {
    if (running && open) restart();
    else {
      disconnect();
      setPhase("closed");
    }
  }, [running, kind, open]);
  useEffect(() => disconnect, []);

  const submitTotp = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    totp.current = String(new FormData(e.currentTarget).get("code"));
    connect(kind);
  };

  const showGuide = guideOpen && kind === "server" && commands.length > 0;
  // A command line under the terminal: Enter sends it, arrows walk the history.
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!command.trim() || phase !== "open") return;
    ctrl.current?.input(`${command}\r`);
    history.current = [...history.current.filter((c) => c !== command), command].slice(-50);
    back.current = 0;
    setCommand("");
  };
  const walk = (step: 1 | -1) => {
    const h = history.current;
    back.current = Math.min(h.length, Math.max(0, back.current + step));
    setCommand(back.current ? h[h.length - back.current] : "");
  };

  return (
    <CollapsibleCard
      storageKey="app.console"
      className="lg:col-span-2"
      defaultOpen
      onToggle={onToggle}
      title={
        <>
          <SquareTerminal className="size-5" /> {t("console.title")}
          {phase === "open" && <span className="size-2 rounded-full bg-ok" aria-hidden />}
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" className="inline-flex rounded-md border p-0.5">
            {(hasServer ? (["server", "shell"] as Kind[]) : (["shell"] as Kind[])).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                onClick={() => k !== kind && setKind(k)}
                className={cn(
                  "rounded px-3 py-1 text-sm transition-colors",
                  kind === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                )}
              >
                {t(k === "server" ? "console.server" : "console.shell")}
              </button>
            ))}
          </div>
          {kind === "server" && commands.length > 0 && (
            <Button variant="outline" size="sm" aria-pressed={guideOpen} onClick={() => setGuideOpen((v) => !v)}>
              <BookOpen /> {t("console.guide")}
            </Button>
          )}
          {phase === "closed" && running && (
            <Button size="sm" onClick={restart}>
              <RotateCw /> {t("console.reconnect")}
            </Button>
          )}
        </div>
        {!running && <Alert>{t("console.notRunning")}</Alert>}
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
        <div className="min-h-64 flex-1">
          {running && session > 0 && (
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
                connect(kind);
              }}
            />
          )}
        </div>
        {running && (
          <form onSubmit={send} className="flex gap-2">
            <Input
              ref={line}
              aria-label={t("console.command")}
              placeholder={t("console.commandPlaceholder")}
              className="font-mono"
              value={command}
              disabled={phase !== "open"}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                setCommand(e.target.value);
                back.current = 0;
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowUp" || e.key === "ArrowDown") {
                  e.preventDefault();
                  walk(e.key === "ArrowUp" ? 1 : -1);
                }
              }}
            />
            <Button type="submit" disabled={phase !== "open" || !command.trim()}>
              <CornerDownLeft /> {t("console.send")}
            </Button>
          </form>
        )}
        {showGuide && running && (
          <div className="animate-enter grid gap-1.5" role="group" aria-label={t("console.guide")}>
            <p className="text-xs text-muted-foreground">{t("console.guideHint")}</p>
            <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
              {commands.map((c) => (
                <button
                  key={c.command}
                  type="button"
                  title={l(c.description)}
                  disabled={phase !== "open"}
                  onClick={() => {
                    setCommand(c.command);
                    line.current?.focus();
                  }}
                  className="rounded-full border bg-card px-2.5 py-1 font-mono text-xs transition-[background-color,translate] duration-200 ease-(--ease-spring) hover:-translate-y-0.5 hover:bg-muted disabled:opacity-50"
                >
                  {c.command}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </CollapsibleCard>
  );
}
