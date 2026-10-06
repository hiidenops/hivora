"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  api,
  type HostedSiteIn,
  type JobRef,
  type SiteChange,
  type SiteHost,
  type SitePlan,
} from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";

// Under the app's key: the live updates that refresh the apps refresh its sites too.
export const hostKey = (appId: number) => [...keys.app(appId), "sites"] as const;

/** The sites an nginx hosts; `notHost` when it serves one site only (404 site_not_found). */
export function useHostedSites(appId: number) {
  const query = useQuery({
    queryKey: hostKey(appId),
    queryFn: () => api<SiteHost>(`/apps/${appId}/sites`),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const notHost = query.error instanceof ApiError && query.error.code === "site_not_found";
  return { ...query, notHost };
}

function useHostMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: keys.apps }) });
}

export const useEnableHosting = (appId: number) =>
  useHostMutation(() => api<SiteHost>(`/apps/${appId}/sites/hosting`, { method: "POST" }));

/** A preview: nothing is written. */
export const usePlanSite = (appId: number) =>
  useMutation({ mutationFn: (body: HostedSiteIn) => api<SitePlan>(`/apps/${appId}/sites/plan`, { method: "POST", body }) });

export const useAddSite = (appId: number) =>
  useHostMutation((body: HostedSiteIn) => api<SiteChange>(`/apps/${appId}/sites`, { method: "POST", body }));

export const useSetHostedSiteEnabled = (appId: number) =>
  useHostMutation(({ siteId, enabled }: { siteId: number; enabled: boolean }) =>
    api<JobRef>(`/apps/${appId}/sites/${siteId}/enabled`, { method: "PUT", body: { enabled } }),
  );

/** Previews: nothing is written. */
export const usePlanPort = (appId: number, siteId: number) =>
  useMutation({ mutationFn: (port: number) => api<SitePlan>(`/apps/${appId}/sites/${siteId}/port/plan`, { method: "POST", body: { port } }) });

export const useRemovalPlan = (appId: number, siteId: number, enabled: boolean) =>
  useQuery({
    queryKey: [...hostKey(appId), siteId, "removal"],
    queryFn: () => api<SitePlan>(`/apps/${appId}/sites/${siteId}/removal-plan`),
    enabled,
    retry: false,
    gcTime: 0,
  });

export const useChangePort = (appId: number, siteId: number) =>
  useHostMutation((port: number) => api<SiteChange>(`/apps/${appId}/sites/${siteId}/port`, { method: "PUT", body: { port } }));

export const useSetServerName = (appId: number, siteId: number) =>
  useHostMutation((serverName: string | null) =>
    api<JobRef>(`/apps/${appId}/sites/${siteId}/server-name`, { method: "PUT", body: { server_name: serverName } }),
  );

export const useRemoveSite = (appId: number, siteId: number) =>
  useHostMutation((removeData: boolean) =>
    api<SiteChange>(`/apps/${appId}/sites/${siteId}?remove_data=${removeData}`, { method: "DELETE" }),
  );
