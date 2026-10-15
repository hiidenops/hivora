/** What the Updates card says about the available version. */
export type UpdateState = "off" | "unavailable" | "newer" | "upToDate" | "none" | "unknown";

export function updateState(r: {
  enabled: boolean;
  available: boolean;
  newer: boolean;
  latest: unknown;
  error?: string | null;
}): UpdateState {
  if (!r.enabled) return "off"; // nothing asked: nothing known
  if (!r.available) return "unavailable"; // the source is not on GitHub
  if (r.newer) return "newer";
  if (r.latest) return "upToDate";
  return r.error ? "unknown" : "none"; // offline before any answer, or no release yet
}
