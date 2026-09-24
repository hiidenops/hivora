"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";

import { keys } from "@/lib/api/hooks";
import type { AppStatus, HostSample } from "@/lib/api/client";

export interface LiveJob {
  status: string;
  progress: number;
  message: string | null;
  error: string | null;
  lines: string[];
}

/** One per-app usage sample (every 5 s while someone watches the app). */
export interface AppSample {
  ts: number;
  cpu_percent: number; // % of the whole machine
  mem_bytes: number;
  mem_limit: number;
  net_rx_bps: number;
  net_tx_bps: number;
}

export type Message = Record<string, unknown> & { channel?: string; type?: string };
const MAX_LINES = 2000;

/** One WebSocket per tab; the UI subscribes to slices of this store. */
class RealtimeStore {
  private ws: WebSocket | null = null;
  private listeners = new Set<() => void>();
  private watchedJobs = new Set<number>();
  private watchedApps = new Map<string, number>(); // slug -> watching components
  private consoles = new Map<string, (msg: Message) => void>();
  private retry = 0;
  private closed = false;
  onJobFinished: ((msg: Message) => void) | null = null;
  onAppChanged: (() => void) | null = null;
  connected = false;
  statuses: Record<string, AppStatus> = {};
  jobs: Record<number, LiveJob> = {};
  host: HostSample[] = [];
  appMetrics: Record<string, AppSample[]> = {};

  connect() {
    this.closed = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.connected = true;
      this.send({ op: "subscribe", channel: "state" });
      this.send({ op: "subscribe", channel: "jobs" });
      this.send({ op: "subscribe", channel: "metrics" });
      this.watchedJobs.forEach((id) => this.send({ op: "subscribe", channel: "job", id }));
      this.watchedApps.forEach((_, app) => this.send({ op: "subscribe", channel: "app_metrics", app }));
      this.emit();
    };
    ws.onmessage = (e) => this.handle(JSON.parse(e.data) as Message);
    ws.onclose = (e) => {
      this.connected = false;
      this.emit();
      // 4401/4403: session gone or password change pending; the app shell redirects.
      if (this.closed || e.code === 4401 || e.code === 4403) return;
      const delay = Math.min(30_000, 500 * 2 ** this.retry++);
      setTimeout(() => !this.closed && this.connect(), delay);
    };
  }

  disconnect() {
    this.closed = true;
    this.ws?.close();
  }

  watchJob(id: number) {
    if (this.watchedJobs.has(id)) return;
    this.watchedJobs.add(id);
    this.jobs[id] ??= { status: "queued", progress: 0, message: null, error: null, lines: [] };
    this.send({ op: "subscribe", channel: "job", id });
  }

  /** Streams an app's usage while at least one component watches it. */
  watchApp(app: string) {
    const count = this.watchedApps.get(app) ?? 0;
    this.watchedApps.set(app, count + 1);
    if (!count) this.send({ op: "subscribe", channel: "app_metrics", app });
    return () => {
      const left = (this.watchedApps.get(app) ?? 1) - 1;
      if (left) return void this.watchedApps.set(app, left);
      this.watchedApps.delete(app);
      this.send({ op: "unsubscribe", channel: "app_metrics", app });
      const { [app]: _dropped, ...rest } = this.appMetrics;
      this.appMetrics = rest;
    };
  }

  /** Opens a console on the shared socket; `onMessage` gets opened/data/closed/error. */
  openConsole(open: Record<string, unknown>, onMessage: (msg: Message) => void) {
    const id = String(open.id);
    this.consoles.set(id, onMessage);
    this.send({ op: "console.open", ...open });
    return {
      input: (data: string) => this.send({ op: "console.input", id, data }),
      resize: (rows: number, cols: number) => this.send({ op: "console.resize", id, rows, cols }),
      close: () => {
        this.send({ op: "console.close", id });
        this.consoles.delete(id);
      },
    };
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  private send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private emit() {
    this.listeners.forEach((fn) => fn());
  }

  private updateJob(id: number, patch: Partial<LiveJob>) {
    const current = this.jobs[id] ?? { status: "queued", progress: 0, message: null, error: null, lines: [] };
    this.jobs = { ...this.jobs, [id]: { ...current, ...patch } };
  }

  private handle(msg: Message) {
    if (msg.channel === "console") {
      this.consoles.get(String(msg.id))?.(msg);
      return;
    }
    if (msg.channel === "app_metrics") {
      const app = msg.app as string;
      const samples =
        msg.type === "snapshot"
          ? (msg.samples as AppSample[])
          : [...(this.appMetrics[app] ?? []), msg as unknown as AppSample].slice(-60);
      this.appMetrics = { ...this.appMetrics, [app]: samples };
    } else if (msg.channel === "metrics") {
      this.host = [...this.host, msg as unknown as HostSample].slice(-1800);
    } else if (msg.channel === "state") {
      if (msg.type === "snapshot") this.statuses = msg.apps as Record<string, AppStatus>;
      else this.statuses = { ...this.statuses, [msg.app as string]: msg.status as AppStatus };
      this.onAppChanged?.();
    } else if (msg.channel === "jobs" && typeof msg.id === "number" && this.watchedJobs.has(msg.id)) {
      if (msg.type === "started") this.updateJob(msg.id, { status: "running" });
      if (msg.type === "progress")
        this.updateJob(msg.id, { progress: msg.progress as number, message: (msg.message as string) ?? null });
      if (msg.type === "finished")
        this.updateJob(msg.id, { status: msg.status as string, error: (msg.error as string) ?? null, progress: 100 });
    } else if (msg.channel === "job" && typeof msg.id === "number") {
      const lines = [...(this.jobs[msg.id]?.lines ?? []), msg.line as string].slice(-MAX_LINES);
      this.updateJob(msg.id, { lines });
    }
    if (msg.channel === "jobs" && msg.type === "finished") this.onJobFinished?.(msg);
    this.emit();
  }
}

const RealtimeContext = createContext<RealtimeStore | null>(null);

export function RealtimeProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const store = useRef<RealtimeStore>(null);
  store.current ??= new RealtimeStore();
  const qc = useQueryClient();

  useEffect(() => {
    const s = store.current!;
    if (!enabled) return;
    s.onJobFinished = () => {
      void qc.invalidateQueries({ queryKey: keys.apps });
      void qc.invalidateQueries({ queryKey: keys.jobs });
    };
    s.onAppChanged = () => void qc.invalidateQueries({ queryKey: keys.apps });
    s.connect();
    return () => s.disconnect();
  }, [enabled, qc]);

  return <RealtimeContext.Provider value={store.current}>{children}</RealtimeContext.Provider>;
}

function useStore(): RealtimeStore {
  const s = useContext(RealtimeContext);
  if (!s) throw new Error("useRealtime outside RealtimeProvider");
  return s;
}

export function useConnected(): boolean {
  const s = useStore();
  return useSyncExternalStore(s.subscribe, () => s.connected, () => false);
}

export function useLiveStatus(slug: string, fallback: AppStatus): AppStatus {
  const s = useStore();
  return useSyncExternalStore(s.subscribe, () => s.statuses[slug] ?? fallback, () => fallback);
}

export function useLiveJob(id: number | null): LiveJob | null {
  const s = useStore();
  useEffect(() => {
    if (id) s.watchJob(id);
  }, [id, s]);
  return useSyncExternalStore(s.subscribe, () => (id ? (s.jobs[id] ?? null) : null), () => null);
}

/** Host samples received since the page connected (history comes from REST). */
export function useLiveHost(): HostSample[] {
  const s = useStore();
  return useSyncExternalStore(s.subscribe, () => s.host, () => EMPTY);
}
const EMPTY: HostSample[] = [];

/** Live usage of one app; sampling runs server-side only while this is mounted. */
export function useAppMetrics(slug: string, enabled: boolean): AppSample[] {
  const s = useStore();
  useEffect(() => (enabled ? s.watchApp(slug) : undefined), [slug, enabled, s]);
  return useSyncExternalStore(s.subscribe, () => s.appMetrics[slug] ?? NO_SAMPLES, () => NO_SAMPLES);
}
const NO_SAMPLES: AppSample[] = [];

export function useRealtime(): RealtimeStore {
  return useStore();
}
