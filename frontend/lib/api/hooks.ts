"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import {
  api,
  setCsrfToken,
  type App,
  type AppDetail,
  type AppSettings,
  type AuditEntry,
  type DeployIn,
  type Job,
  type JobDetail,
  type JobRef,
  type Me,
  type Plan,
  type RemovalPlan,
  type Revision,
  type Role,
  type SessionInfo,
  type TemplateDetail,
  type SystemInfo,
  type SystemStatus,
  type Health,
  type Releases,
  type TemplateSummary,
  type UpdatePlan,
  type User,
  type Zone,
} from "./client";

export const keys = {
  me: ["me"] as const,
  apps: ["apps"] as const,
  app: (id: number) => ["apps", id] as const,
  // Sites: refreshed when a job of their app ends (invalidateSitesOf), not on every
  // container state change.
  siteHosts: ["site-hosts"] as const,
  siteFiles: ["site-files"] as const,
  // Topology, VPN and game panels: not under "apps" (refreshed by invalidateAppViews when
  // an app changes state or a job of it ends, not on every apps list refresh).
  topology: ["topology"] as const,
  vpn: (id: number) => ["vpn", id] as const,
  game: (id: number) => ["game", id] as const,
  templates: ["templates"] as const,
  template: (slug: string) => ["templates", slug] as const,
  jobs: ["jobs"] as const,
  job: (id: number) => ["jobs", id] as const,
  users: ["users"] as const,
  zones: ["zones"] as const,
  audit: ["audit"] as const,
};

/** Ids of the app `slug` among the apps in cache (the list, a detail page). */
function cachedAppIds(qc: QueryClient, slug: string): number[] {
  const ids = new Set<number>();
  for (const [, data] of qc.getQueriesData<unknown>({ queryKey: keys.apps })) {
    for (const row of Array.isArray(data) ? data : [data]) {
      const app = row as { id?: unknown; slug?: unknown } | null;
      if (app?.slug === slug && typeof app.id === "number") ids.add(app.id);
    }
  }
  return [...ids];
}

/** One app's VPN and game panels read again. */
export function invalidateAppPanels(qc: QueryClient, id: number) {
  void qc.invalidateQueries({ queryKey: keys.vpn(id) });
  void qc.invalidateQueries({ queryKey: keys.game(id) });
}

/** The app `slug` changed state or a job of it ended: the topology and that app's panels
 *  read again (every app's when the slug is unknown, e.g. the state snapshot on reconnect). */
export function invalidateAppViews(qc: QueryClient, slug: string | undefined) {
  void qc.invalidateQueries({ queryKey: keys.topology });
  if (slug === undefined) {
    void qc.invalidateQueries({ queryKey: ["vpn"] });
    void qc.invalidateQueries({ queryKey: ["game"] });
    return;
  }
  for (const id of cachedAppIds(qc, slug)) invalidateAppPanels(qc, id);
}

/** A job of the app `slug` ended: its hosted sites and their files read again, no other
 *  host's (the hosts in cache tell which app ids that slug is). */
export function invalidateSitesOf(qc: QueryClient, slug: string | undefined) {
  if (!slug) return;
  const ids = qc
    .getQueriesData<{ app_id?: number; slug?: string }>({ queryKey: keys.siteHosts })
    .flatMap(([, host]) => (host?.slug === slug && host.app_id !== undefined ? [host.app_id] : []));
  for (const id of ids) {
    void qc.invalidateQueries({ queryKey: [...keys.siteHosts, id] });
    void qc.invalidateQueries({
      queryKey: keys.siteFiles,
      predicate: (q) => String(q.queryKey[1]).startsWith(`/apps/${id}/`),
    });
  }
}

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      const me = await api<Me>("/auth/me");
      setCsrfToken(me.csrf_token);
      return me;
    },
    retry: false,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string; totp_code?: string }) =>
      api<Me>("/auth/login", { method: "POST", body }),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token);
      qc.setQueryData(keys.me, me);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      setCsrfToken(null);
      qc.clear();
    },
  });
}

export function useChangePassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { current: string; new: string }) =>
      api<void>("/auth/password", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}

export const useApps = () => useQuery({ queryKey: keys.apps, queryFn: () => api<App[]>("/apps") });
export const useApp = (id: number) =>
  useQuery({ queryKey: keys.app(id), queryFn: () => api<AppDetail>(`/apps/${id}`), enabled: id > 0 });
export const useAppCompose = (id: number, enabled: boolean) =>
  useQuery({
    queryKey: [...keys.app(id), "compose"],
    queryFn: () => api<{ compose_yaml: string }>(`/apps/${id}/compose`),
    enabled,
  });
export const useRevisions = (id: number, enabled: boolean) =>
  useQuery({
    queryKey: [...keys.app(id), "revisions"],
    queryFn: () => api<Revision[]>(`/apps/${id}/revisions`),
    enabled,
  });
export const useRemovalPlan = (id: number, enabled: boolean) =>
  useQuery({
    queryKey: [...keys.app(id), "removal"],
    queryFn: () => api<RemovalPlan>(`/apps/${id}/removal-plan`),
    enabled,
  });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/system/health"), staleTime: 300_000 });
/** The System page's checks (admins); refreshed every 5 minutes for the sidebar's dot. */
export const useSystemStatus = (enabled: boolean) =>
  useQuery({
    queryKey: ["system-status"],
    queryFn: () => api<SystemStatus>("/system/status"),
    enabled,
    staleTime: 300_000,
    refetchInterval: 300_000,
  });
/** Available versions (admins): GitHub is asked at most every 12 h by the server. */
export const useReleases = (enabled: boolean) =>
  useQuery({
    queryKey: ["system-releases"],
    queryFn: () => api<Releases>("/system/releases"),
    enabled,
    staleTime: 3_600_000,
    refetchInterval: 3_600_000,
  });
export const useSystemInfo = () =>
  useQuery({ queryKey: ["system-info"], queryFn: () => api<SystemInfo>("/system/info"), staleTime: 300_000 });
export const useTemplates = () =>
  useQuery({ queryKey: keys.templates, queryFn: () => api<TemplateSummary[]>("/templates"), staleTime: 300_000 });
export const useTemplate = (slug: string) =>
  useQuery({
    queryKey: keys.template(slug),
    queryFn: () => api<TemplateDetail>(`/templates/${slug}`),
    enabled: !!slug,
    staleTime: 300_000,
  });
export const useZones = () => useQuery({ queryKey: keys.zones, queryFn: () => api<Zone[]>("/zones") });

/** Create (no slug) or edit a zone. */
export function useSaveZone(slug?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; color: string; network_mode: string }) =>
      api<Zone>(slug ? `/zones/${slug}` : "/zones", { method: slug ? "PUT" : "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.zones });
      void qc.invalidateQueries({ queryKey: keys.apps });
    },
  });
}

export function useDeleteZone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => api<void>(`/zones/${slug}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.zones }),
  });
}

export function useMoveZone(appId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (zone: string | null) => api<JobRef>(`/apps/${appId}/zone`, { method: "PUT", body: { zone } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.app(appId) });
      invalidateAppPanels(qc, appId);
      void qc.invalidateQueries({ queryKey: keys.zones });
    },
  });
}

export const useJobs = (appId?: number) =>
  useQuery({
    queryKey: appId ? [...keys.jobs, { appId }] : keys.jobs,
    queryFn: () => api<Job[]>("/jobs", { query: { limit: "30", ...(appId ? { app_id: String(appId) } : {}) } }),
  });
export const useJob = (id: number | null) =>
  useQuery({ queryKey: keys.job(id ?? 0), queryFn: () => api<JobDetail>(`/jobs/${id}`), enabled: !!id });

export const usePlan = () =>
  useMutation({ mutationFn: (body: DeployIn) => api<Plan>("/apps/plan", { method: "POST", body }) });

export function useDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DeployIn) => api<{ app: App; job: JobRef }>("/apps", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }),
  });
}

export type AppAction = "start" | "stop" | "restart";

export function useAppAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: AppAction }) =>
      api<JobRef>(`/apps/${id}/${action}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }),
  });
}

export function useRemoveApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, removeData }: { id: number; removeData: boolean }) =>
      api<JobRef>(`/apps/${id}`, { method: "DELETE", query: { remove_data: String(removeData) } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }),
  });
}

export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: () => api<User[]>("/users") });

export function useUserMutation<V>(fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }) });
}

export const userApi = {
  create: (b: { username: string; role: Role; password: string }) =>
    api<User>("/users", { method: "POST", body: b }),
  update: ({ id, ...b }: { id: number; role?: Role; disabled?: boolean }) =>
    api<User>(`/users/${id}`, { method: "PATCH", body: b }),
  remove: (id: number) => api<void>(`/users/${id}`, { method: "DELETE" }),
  resetPassword: ({ id, temporary }: { id: number; temporary: string }) =>
    api<void>(`/users/${id}/password`, { method: "POST", body: { temporary } }),
  resetTotp: (id: number) => api<void>(`/users/${id}/totp/reset`, { method: "POST" }),
  revokeSessions: (id: number) => api<void>(`/users/${id}/sessions`, { method: "DELETE" }),
};

export const useAudit = () => useQuery({ queryKey: keys.audit, queryFn: () => api<AuditEntry[]>("/audit") });
export const useMySessions = () =>
  useQuery({ queryKey: ["sessions"], queryFn: () => api<SessionInfo[]>("/auth/sessions") });

export const useAppSettings = (id: number) =>
  useQuery({ queryKey: [...keys.app(id), "settings"], queryFn: () => api<AppSettings>(`/apps/${id}/settings`), enabled: id > 0 });

export const usePlanUpdate = (id: number) =>
  useMutation({
    mutationFn: ({ inputs, overrides }: { inputs: Record<string, unknown>; overrides?: unknown }) =>
      api<UpdatePlan>(`/apps/${id}/settings/plan`, { method: "POST", body: { inputs, overrides } }),
  });

export function useUpdateSettings(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ inputs, resetData, overrides }: { inputs: Record<string, unknown>; resetData: boolean; overrides?: unknown }) =>
      api<JobRef>(`/apps/${id}/settings`, { method: "PUT", body: { inputs, reset_data: resetData, overrides } }),
    onSuccess: () => {
      invalidateAppPanels(qc, id);
      return qc.invalidateQueries({ queryKey: keys.app(id) }); // awaited, as before
    },
  });
}
