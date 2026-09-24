import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type App = Schemas["AppOut"];
export type AppDetail = Schemas["AppDetailOut"];
export type AppStatus = App["status"];
export type Plan = Schemas["PlanOut"];
export type DeployIn = Schemas["DeployIn"];
export type JobRef = Schemas["JobRef"];
export type Job = Schemas["JobOut"];
export type JobDetail = Schemas["JobDetailOut"];
export type TemplateSummary = Schemas["TemplateSummary"];
export type TemplateDetail = Schemas["TemplateDetail"];
export type User = Schemas["UserOut"];
export type Role = User["role"];
export type Zone = Schemas["ZoneOut"];
export type AuditEntry = Schemas["AuditOut"];
export type Revision = Schemas["RevisionOut"];
export type RemovalPlan = Schemas["RemovalPlanOut"];
export type SessionInfo = Schemas["SessionOut"];
export type HostSample = Schemas["HostSampleOut"];
export type AppSettings = Schemas["SettingsOut"];
export type UpdatePlan = Schemas["UpdatePlanOut"];
export type Modpack = Schemas["ModpackOut"];
export type Integrations = Schemas["IntegrationsOut"];

/** Error returned by the backend: `code` is stable and translated by the UI. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export async function api<T>(
  path: string,
  { method = "GET", body, query }: { method?: string; body?: unknown; query?: Record<string, string> } = {},
): Promise<T> {
  const url = `/api/v1${path}${query ? `?${new URLSearchParams(query)}` : ""}`;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? res.statusText, err.details);
  }
  return data as T;
}
