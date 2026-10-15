import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { NextConfig } from "next";

// The version this frontend was built from (package.json, which copies pyproject.toml's):
// compared with the server's, a stale page in the browser is told to reload.
const { version } = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8"));

const isDev = process.env.NODE_ENV === "development";
const backend = process.env.HIVORA_BACKEND ?? "http://127.0.0.1:8000";

// Production: static SPA served by FastAPI (no Node runtime).
// Development: `next dev` proxies the API and WebSocket to the backend.
const nextConfig: NextConfig = {
  ...(isDev
    ? {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${backend}/api/:path*` },
            { source: "/ws", destination: `${backend}/ws` },
          ];
        },
      }
    : { output: "export" }),
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  env: { NEXT_PUBLIC_HIVORA_VERSION: version },
};

export default nextConfig;
