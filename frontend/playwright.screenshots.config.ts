import { defineConfig, devices } from "@playwright/test";

import { HOST } from "./e2e/host";

// The README's screenshots (docs/images/): `npx playwright test -c playwright.screenshots.config.ts`.
// Never in the CI's e2e run. A fresh panel with demo data (HIVORA_E2E_DEMO), a fake Docker.
const PORT = 18510;
const DATA = "/tmp/hivora-e2e-screenshots";

export default defineConfig({
  testDir: "e2e/screenshots",
  timeout: 120_000,
  workers: 1,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: `http://${HOST}:${PORT}`,
    locale: "en-US",
    colorScheme: "light",
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command:
      `rm -rf ${DATA} && cd ../backend && HIVORA_E2E_DEMO=1 ` +
      `HIVORA_DATA_DIR=${DATA}/data HIVORA_VOLUMES_ROOT=${DATA}/srv HIVORA_CATALOG_DIR=../templates ` +
      `HIVORA_FRONTEND_DIR=../frontend/out HIVORA_DEV_INSECURE_COOKIES=true HIVORA_HOST_PUBLIC_IP=203.0.113.7 ` +
      `HIVORA_HOST_LAN_IP=${HOST} ` +
      `uv run uvicorn --factory e2e_app:app --app-dir tests --host 0.0.0.0 --port ${PORT}`,
    url: `http://${HOST}:${PORT}/api/v1/system/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
