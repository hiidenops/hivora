import { networkInterfaces } from "node:os";

import { defineConfig, devices } from "@playwright/test";

const PORT = 18500;
const DATA = "/tmp/hivora-e2e";
// Browse through the LAN IP, like real users: plain HTTP there is NOT a secure
// context (unlike 127.0.0.1), so HTTPS-only browser APIs break the tests too.
const HOST =
  Object.values(networkInterfaces())
    .flat()
    .find((i) => i && i.family === "IPv4" && !i.internal)?.address ?? "127.0.0.1";

// Runs against the exported UI served by the real backend, with a fake Docker.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://${HOST}:${PORT}`, locale: "fr-FR", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      `rm -rf ${DATA} && cd ../backend && ` +
      `HIVORA_DATA_DIR=${DATA}/data HIVORA_VOLUMES_ROOT=${DATA}/srv HIVORA_CATALOG_DIR=../templates ` +
      `HIVORA_FRONTEND_DIR=../frontend/out HIVORA_DEV_INSECURE_COOKIES=true HIVORA_HOST_PUBLIC_IP=203.0.113.7 ` +
      `HIVORA_HOST_LAN_IP=${HOST} ` + // as install.sh sets it: apps get a real address
      `uv run uvicorn --factory e2e_app:app --app-dir tests --host 0.0.0.0 --port ${PORT}`,
    url: `http://${HOST}:${PORT}/api/v1/system/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
