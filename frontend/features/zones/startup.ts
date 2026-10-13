import { api } from "@/lib/api/client";

import type { Dep } from "./order";

// A zone's start order as the server gives it; light (the graph module loads React Flow).
export type Startup = {
  zone: string;
  timeout_s: number;
  apps: { id: number; slug: string; name: string; status: string }[];
  dependencies: Dep[];
  steps: number[][];
};

export const startupKey = (slug: string) => ["zones", slug, "startup"] as const;
export const fetchStartup = (slug: string) => api<Startup>(`/zones/${slug}/startup`);
