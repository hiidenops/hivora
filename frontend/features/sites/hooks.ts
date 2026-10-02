"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type JobRef, type Site, type SiteCreated, type SiteIn } from "@/lib/api/client";
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
