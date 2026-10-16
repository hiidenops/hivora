import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-battery";
const OUT = "../docs/images";

/** Signed in through the API (the first password change done), then the panel opened. */
async function signIn(page: Page) {
  const first = await page.request.post("/api/v1/auth/login", { data: { username: "admin", password: "admin" } });
  expect(first.ok()).toBe(true);
  const headers = { "X-CSRF-Token": (await first.json()).csrf_token as string };
  expect((await page.request.post("/api/v1/auth/password", { headers, data: { current: "admin", new: PASSWORD } })).ok()).toBe(true);
  const again = await page.request.post("/api/v1/auth/login", { data: { username: "admin", password: PASSWORD } });
  return { "X-CSRF-Token": (await again.json()).csrf_token as string };
}

async function deploy(page: Page, headers: Record<string, string>, template: string, name: string, zone: string, inputs: object = {}) {
  const r = await page.request.post("/api/v1/apps", { headers, data: { template, name, zone, inputs } });
  expect(r.ok(), await r.text()).toBe(true);
  const job = (await r.json()).job.id as number;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${job}`)).json()).status, { timeout: 60_000 }).toBe("succeeded");
}

test("README screenshots", async ({ page }) => {
  const headers = await signIn(page);
  for (const [name, color] of [["Médias", "#7c3aed"], ["Jeux", "#16a34a"], ["Maison", "#0284c7"]]) {
    await page.request.post("/api/v1/zones", { headers, data: { name, color, network_mode: "shared" } });
  }
  await deploy(page, headers, "jellyfin", "Jellyfin", "medias");
  await deploy(page, headers, "immich", "Immich", "medias");
  await deploy(page, headers, "minecraft", "Minecraft", "jeux", { eula: true });
  await deploy(page, headers, "terraria", "Terraria", "jeux");
  await deploy(page, headers, "home-assistant", "Home Assistant", "maison");
  await deploy(page, headers, "vaultwarden", "Vaultwarden", "maison");
  await deploy(page, headers, "uptime-kuma", "Uptime Kuma", "administration");

  await page.goto("/");
  await expect(page.getByText("Jellyfin").first()).toBeVisible();
  await page.waitForTimeout(1500); // the cards' entrance animation
  await page.screenshot({ path: `${OUT}/dashboard.png` });

  await page.goto("/catalog/");
  await page.getByRole("heading", { name: "Applications" }).click();
  await expect(page.getByText("Nextcloud").first()).toBeVisible();
  await page.mouse.move(0, 799); // no hovered card
  await page.waitForTimeout(2500); // icons
  await page.screenshot({ path: `${OUT}/catalog.png` });

  await page.goto("/settings/");
  const heading = page.getByRole("heading", { name: "Santé du panel" });
  await heading.waitFor();
  await page.waitForTimeout(1500); // the cards' entrance animation
  await heading.evaluate((el) => { el.scrollIntoView({ block: "start" }); window.scrollBy(0, -48); }); // the whole card, a margin above
  await page.mouse.move(0, 799);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/health.png` }); // the whole window, as the others
});
