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
export type SystemInfo = Schemas["SystemInfo"];
export type SystemStatus = Schemas["StatusOut"];
export type SystemCheck = Schemas["CheckOut"];
export type Health = Schemas["Health"];
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
export type Players = Schemas["PlayersOut"];
export type GameCaps = Schemas["GameCapsOut"];
export type GameLists = Schemas["ListsOut"];
export type Worlds = Schemas["WorldsOut"];
export type SiteFiles = Schemas["SiteFilesOut"];
export type SiteTextFile = Schemas["SiteTextFileOut"];
export type SiteFileIn = Schemas["SiteFileIn"];
export type SiteHost = Schemas["SiteHostOut"];
export type HostedSite = Schemas["HostedSiteOut"];
export type HostedSiteIn = Schemas["HostedSiteIn"];
export type SitePlan = Schemas["SitePlanOut"];
export type SiteChange = Schemas["SiteChangeOut"];

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
    // A public panel and no TOTP yet (e.g. reset by an admin meanwhile): set it up first.
    if (err.code === "totp_setup_required" && location.pathname !== "/setup-totp/") location.assign("/setup-totp/");
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? res.statusText, err.details);
  }
  return data as T;
}

/** Sends a file as the raw request body; XHR because fetch reports no upload progress. */
export function upload<T>(
  path: string,
  file: Blob,
  {
    query,
    onProgress,
    method = "POST",
  }: { query?: Record<string, string>; onProgress?: (fraction: number) => void; method?: "POST" | "PUT" } = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, `/api/v1${path}${query ? `?${new URLSearchParams(query)}` : ""}`);
    xhr.setRequestHeader("Content-Type", "application/zip");
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "http_error", "network error"));
    xhr.onload = () => {
      let data: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON answer */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data as T);
      const err = data?.error ?? {};
      reject(new ApiError(xhr.status, err.code ?? "http_error", err.message ?? xhr.statusText, err.details));
    };
    xhr.send(file);
  });
}
