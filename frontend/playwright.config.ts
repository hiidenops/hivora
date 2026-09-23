import { defineConfig, devices } from "@playwright/test";

const PORT = 18500;
const DATA = "/tmp/hivora-e2e";

// Runs against the exported UI served by the real backend, with a fake Docker.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://127.0.0.1:${PORT}`, locale: "fr-FR", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      `rm -rf ${DATA} && cd ../backend && ` +
      `HIVORA_DATA_DIR=${DATA}/data HIVORA_VOLUMES_ROOT=${DATA}/srv HIVORA_CATALOG_DIR=../templates ` +
      `HIVORA_FRONTEND_DIR=../frontend/out HIVORA_DEV_INSECURE_COOKIES=true ` +
      `uv run uvicorn --factory e2e_app:app --app-dir tests --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/system/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
