import { defineConfig, devices } from "@playwright/test";

import { HOST, PORT, PUBLIC_PORT, VPN_PORT } from "./e2e/host";

const DATA = "/tmp/hivora-e2e";

/** The backend serving the exported UI, on its own fresh data folder. */
function server(port: number, data: string, env = "") {
  return {
    command:
      `rm -rf ${data} && cd ../backend && ${env}` +
      `HIVORA_DATA_DIR=${data}/data HIVORA_VOLUMES_ROOT=${data}/srv HIVORA_CATALOG_DIR=../templates ` +
      `HIVORA_FRONTEND_DIR=../frontend/out HIVORA_DEV_INSECURE_COOKIES=true HIVORA_HOST_PUBLIC_IP=203.0.113.7 ` +
      `HIVORA_HOST_LAN_IP=${HOST} ` + // as install.sh sets it: apps get a real address
      `uv run uvicorn --factory e2e_app:app --app-dir tests --host 0.0.0.0 --port ${port}`,
    url: `http://${HOST}:${port}/api/v1/system/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  };
}

// Runs against the exported UI served by the real backend, with a fake Docker.
export default defineConfig({
  testDir: "e2e",
  testIgnore: ["screenshots/**"], // the README's screenshots: playwright.screenshots.config.ts
  timeout: 60_000,
  // One server and one database for every file: the files run one after another, in name
  // order (apps.spec.ts first: its first-start test needs the fresh instance).
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://${HOST}:${PORT}`, locale: "fr-FR", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // The second one is a public panel (public-totp.spec.ts only), the third one has the
  // admin VPN (admin-vpn.spec.ts only).
  webServer: [
    server(PORT, DATA),
    server(PUBLIC_PORT, `${DATA}-public`, "HIVORA_ACCESS=public "),
    server(VPN_PORT, `${DATA}-vpn`, "HIVORA_ACCESS=vpn "),
  ],
});
