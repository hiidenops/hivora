import type { NextConfig } from "next";

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
};

export default nextConfig;
