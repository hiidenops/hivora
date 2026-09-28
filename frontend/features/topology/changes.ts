import { api, type JobRef } from "@/lib/api/client";

/** A change prepared on the topology, applied later as app revisions (or discarded). */
export type Change =
  | { kind: "move"; appId: number; app: string; zone: string | null; zoneLabel: string }
  | { kind: "expose"; appId: number; app: string; service: string; port: string; exposure: "public" | "lan" | "none" }
  | { kind: "reach"; vpnId: number; vpn: string; target: string; targetLabel: string; on: boolean };

export const changeKey = (c: Change) =>
  c.kind === "move" ? `move:${c.appId}` : c.kind === "expose" ? `expose:${c.appId}:${c.service}:${c.port}` : `reach:${c.vpnId}:${c.target}`;

/** Add or replace (same target), never two changes for one thing. */
export const upsert = (list: Change[], c: Change) => [...list.filter((x) => changeKey(x) !== changeKey(c)), c];

type Settings = { values: Record<string, unknown>; overrides: { services?: Record<string, { publish?: Record<string, string> } & Record<string, unknown>> } };

/**
 * Apply in a safe order: close/open ports first, then VPN links (the app's network
 * exists), then zone moves. Each call starts a job; returns the jobs and errors.
 */
export async function applyChanges(changes: Change[]): Promise<{ jobs: number[]; errors: string[] }> {
  const jobs: number[] = [];
  const errors: string[] = [];
  const run = async (what: string, f: () => Promise<JobRef>) => {
    try {
      jobs.push((await f()).id);
    } catch (e) {
      errors.push(`${what}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const exposures = new Map<number, Extract<Change, { kind: "expose" }>[]>();
  for (const c of changes) if (c.kind === "expose") exposures.set(c.appId, [...(exposures.get(c.appId) ?? []), c]);
  for (const [appId, list] of exposures) {
    await run(list[0].app, async () => {
      const s = await api<Settings>(`/apps/${appId}/settings`);
      const services = { ...(s.overrides.services ?? {}) };
      for (const c of list) {
        const svc = { ...(services[c.service] ?? {}) };
        svc.publish = { ...(svc.publish ?? {}), [c.port]: c.exposure };
        services[c.service] = svc;
      }
      return api<JobRef>(`/apps/${appId}/settings`, { method: "PUT", body: { inputs: s.values, overrides: { services } } });
    });
  }

  const reaches = new Map<number, Extract<Change, { kind: "reach" }>[]>();
  for (const c of changes) if (c.kind === "reach") reaches.set(c.vpnId, [...(reaches.get(c.vpnId) ?? []), c]);
  for (const [vpnId, list] of reaches) {
    await run(list[0].vpn, async () => {
      const current = (await api<{ zones: string[] }>(`/apps/${vpnId}/vpn`)).zones;
      let zones = [...current];
      for (const c of list) zones = c.on ? [...new Set([...zones, c.target])] : zones.filter((z) => z !== c.target);
      return api<JobRef>(`/apps/${vpnId}/vpn/zones`, { method: "PUT", body: { zones } });
    });
  }

  for (const c of changes) {
    if (c.kind === "move") await run(c.app, () => api<JobRef>(`/apps/${c.appId}/zone`, { method: "PUT", body: { zone: c.zone } }));
  }
  return { jobs, errors };
}
