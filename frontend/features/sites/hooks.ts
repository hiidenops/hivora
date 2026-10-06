"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  type JobRef,
  type Site,
  type SiteCreated,
  type SiteFileIn,
  type SiteFiles,
  type SiteIn,
  type SiteTextFile,
} from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";

// Under the apps key: a site is an app, so the live updates that refresh the apps
// (job finished, state changed) refresh the sites too.
export const sitesKey = [...keys.apps, "sites"] as const;

export const useSites = () => useQuery({ queryKey: sitesKey, queryFn: () => api<Site[]>("/sites") });

export function useCreateSite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SiteIn) => api<SiteCreated>("/sites", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }),
  });
}

export function useSetSiteEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api<JobRef>(`/sites/${id}/enabled`, { method: "PUT", body: { enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }),
  });
}

/**
 * The API base of one site's content and files: an app's main site in the older model
 * (`/sites/{app}`), or one site an nginx hosts (`/apps/{app}/sites/{site}`). Both answer
 * the same `/content`, `/files` and `/files/content` routes.
 */
export const siteApi = (appId: number, siteId?: number) =>
  siteId === undefined ? `/sites/${appId}` : `/apps/${appId}/sites/${siteId}`;

export const useSiteFiles = (base: string) =>
  useQuery({ queryKey: [...sitesKey, base, "files"], queryFn: () => api<SiteFiles>(`${base}/files`) });

export const useSiteFile = (base: string, path: string, enabled: boolean) =>
  useQuery({
    queryKey: [...sitesKey, base, "file", path],
    queryFn: () => api<SiteTextFile>(`${base}/files/content?${new URLSearchParams({ path })}`),
    enabled,
  });

/** Queues the save; the file is replaced by the job (base_sha256: null creates it). */
export function useSaveSiteFile(base: string) {
  return useMutation({
    mutationFn: (body: SiteFileIn) => api<JobRef>(`${base}/files/content`, { method: "PUT", body }),
  });
}
