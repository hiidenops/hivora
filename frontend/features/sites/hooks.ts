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

export const useSiteFiles = (id: number) =>
  useQuery({ queryKey: [...sitesKey, id, "files"], queryFn: () => api<SiteFiles>(`/sites/${id}/files`) });

export const useSiteFile = (id: number, path: string, enabled: boolean) =>
  useQuery({
    queryKey: [...sitesKey, id, "file", path],
    queryFn: () => api<SiteTextFile>(`/sites/${id}/files/content?${new URLSearchParams({ path })}`),
    enabled,
  });

/** Queues the save; the file is replaced by the job (base_sha256: null creates it). */
export function useSaveSiteFile(id: number) {
  return useMutation({
    mutationFn: (body: SiteFileIn) => api<JobRef>(`/sites/${id}/files/content`, { method: "PUT", body }),
  });
}
