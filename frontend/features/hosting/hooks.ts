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

// Refreshed when a job ends or after a change made here, not on every state change.
export const hostKey = (appId: number) => [...keys.siteHosts, appId] as const;

/** The sites an nginx hosts. `hosting`: the app's flag (GET /apps); false: not asked for.
 *  `notHost`: it serves one site only (also a 404 site_not_found, if the flag was stale). */
export function useHostedSites(appId: number, hosting = true) {
  const query = useQuery({
    queryKey: hostKey(appId),
    queryFn: () => api<SiteHost>(`/apps/${appId}/sites`),
    enabled: hosting,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const notHost = !hosting || (query.error instanceof ApiError && query.error.code === "site_not_found");
  return { ...query, notHost };
}

/** A change to a host: its sites, and the apps (the hosting flag), read again. */
function useHostMutation<V, R>(appId: number, fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: hostKey(appId) });
      void qc.invalidateQueries({ queryKey: keys.apps });
    },
  });
}

export const useEnableHosting = (appId: number) =>
  useHostMutation(appId, () => api<SiteHost>(`/apps/${appId}/sites/hosting`, { method: "POST" }));

/** A preview: nothing is written. */
export const usePlanSite = (appId: number) =>
  useMutation({ mutationFn: (body: HostedSiteIn) => api<SitePlan>(`/apps/${appId}/sites/plan`, { method: "POST", body }) });

export const useAddSite = (appId: number) =>
  useHostMutation(appId, (body: HostedSiteIn) => api<SiteChange>(`/apps/${appId}/sites`, { method: "POST", body }));

export const useSetHostedSiteEnabled = (appId: number) =>
  useHostMutation(appId, ({ siteId, enabled }: { siteId: number; enabled: boolean }) =>
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
  useHostMutation(appId, (port: number) => api<SiteChange>(`/apps/${appId}/sites/${siteId}/port`, { method: "PUT", body: { port } }));

export const useSetServerName = (appId: number, siteId: number) =>
  useHostMutation(appId, (serverName: string | null) =>
    api<JobRef>(`/apps/${appId}/sites/${siteId}/server-name`, { method: "PUT", body: { server_name: serverName } }),
  );

export const useRemoveSite = (appId: number, siteId: number) =>
  useHostMutation(appId, (removeData: boolean) =>
    api<SiteChange>(`/apps/${appId}/sites/${siteId}?remove_data=${removeData}`, { method: "DELETE" }),
  );

/** nginx's files written again from the sites as recorded (a failed configuration). */
export const useReapplyConfig = (appId: number) =>
  useHostMutation(appId, () => api<JobRef>(`/apps/${appId}/sites/config`, { method: "POST" }));
