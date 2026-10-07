"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  api,
  type JobRef,
  type SiteFileIn,
  type SiteFiles,
  type SiteTextFile,
} from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";

// Refreshed when a job ends (a zip, a save), not when a container's state changes.
export const sitesKey = keys.siteFiles;

/** The API base of one site's content and files: a site an nginx hosts. */
export const siteApi = (appId: number, siteId: number) => `/apps/${appId}/sites/${siteId}`;

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
