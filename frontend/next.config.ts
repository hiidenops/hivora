import type { NextConfig } from "next";

// Static SPA served by FastAPI: no Node runtime in production.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
