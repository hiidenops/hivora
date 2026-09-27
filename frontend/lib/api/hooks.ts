"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
  type TemplateSummary,
  type UpdatePlan,
  type User,
  type Zone,
} from "./client";

export const keys = {
  me: ["me"] as const,
  apps: ["apps"] as const,
  app: (id: number) => ["apps", id] as const,
  templates: ["templates"] as const,
  template: (slug: string) => ["templates", slug] as const,
  jobs: ["jobs"] as const,
  job: (id: number) => ["jobs", id] as const,
  users: ["users"] as const,
  zones: ["zones"] as const,
  audit: ["audit"] as const,
};

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
    mutationFn: (inputs: Record<string, unknown>) =>
      api<UpdatePlan>(`/apps/${id}/settings/plan`, { method: "POST", body: { inputs } }),
  });

export function useUpdateSettings(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ inputs, resetData }: { inputs: Record<string, unknown>; resetData: boolean }) =>
      api<JobRef>(`/apps/${id}/settings`, { method: "PUT", body: { inputs, reset_data: resetData } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.app(id) }),
  });
}
