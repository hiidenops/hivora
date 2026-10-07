import { expect, test } from "@playwright/test";

import { adminApi, deployNginx, expectPointerCursors, signIn } from "./helpers";

// The sites index (/sites): one Sites card per nginx, each site a link to its page; an nginx
// that hosts no sites yet offers to; older bookmarks (/site/?id=) reach the main site.
test("sites index: grouped by nginx, host sites, site links, older bookmarks", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);

  // Asked only for the nginx that host sites: no expected 404 any more.
  const missing: string[] = [];
  page.on("response", (r) => {
    if (r.status() === 404 && r.url().includes("/api/v1/")) missing.push(r.url());
  });

  // No nginx yet (the apps list answered empty, whatever other files deployed): the way
  // to deploy one.
  await page.route("**/api/v1/apps", (route) => route.fulfill({ json: [] }));
  await page.reload(); // the apps list read again (not from the dashboard's cache)
  await page.getByRole("link", { name: "Sites" }).click();
  await expect(page.getByRole("heading", { name: "Sites", level: 1 })).toBeVisible();
  await expect(page.getByText("Aucun nginx pour l'instant", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Nouveau nginx" }).first()).toHaveAttribute("href", "/deploy/?template=nginx");
  await expectPointerCursors(page);
  await page.unroute("**/api/v1/apps");

  // Two nginx (through the API): Vitrine serves one site, Galerie hosts an added one.
  const vitrine = (await deployNginx(page, "Vitrine", 8095)).app.id;
  const galerie = (await deployNginx(page, "Galerie", 8096)).app.id;
  await page.request.post(`/api/v1/apps/${galerie}/sites/hosting`, { headers });
  const photos = await (await page.request.post(`/api/v1/apps/${galerie}/sites`, { headers, data: { name: "Photos", port: 8097 } })).json();
  await done(photos.config_job.id);

  await page.reload();
  const vitrineSites = page.getByRole("list", { name: "Vitrine" });
  const galerieSites = page.getByRole("list", { name: "Galerie" });
  await expect(galerieSites.getByRole("listitem")).toHaveText([/Galerie.*Site principal.*Port 8096/, /Photos.*Port 8097/]);
  await expect(page.getByRole("link", { name: "Galerie", exact: true }).first()).toHaveAttribute("href", `/app/?id=${galerie}`);
  await expect(vitrineSites).toHaveCount(0);
  // Vitrine's own card (other nginx may host no sites either).
  const vitrineCard = page.locator("div.rounded-xl").filter({ has: page.getByRole("link", { name: "Vitrine", exact: true }) });
  await expect(vitrineCard.getByText("Ce nginx sert un seul site", { exact: false })).toBeVisible();

  // Vitrine starts hosting from the index; its main site, off then on.
  await vitrineCard.getByRole("button", { name: "Héberger des sites" }).click();
  await expect(vitrineSites.getByRole("listitem")).toHaveText([/Vitrine.*Site principal.*Port 8095/]);
  const toggle = vitrineSites.getByRole("switch", { name: "Site « Vitrine » actif" });
  await toggle.click();
  await expect(toggle).not.toBeChecked({ timeout: 20_000 });
  await expect(vitrineSites.getByText("Désactivé (répond 503)")).toBeVisible();
  await toggle.click();
  await expect(toggle).toBeChecked({ timeout: 20_000 });
  await expectPointerCursors(page);

  // A job of one host reads its sites again, not the other host's.
  const asked: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url()).pathname;
    if (url.endsWith("/sites")) asked.push(url);
  });
  const restart = await (await page.request.post(`/api/v1/apps/${galerie}/restart`, { headers })).json();
  await done(restart.id);
  await expect.poll(() => asked, { timeout: 10_000 }).toContain(`/api/v1/apps/${galerie}/sites`);
  expect(asked).not.toContain(`/api/v1/apps/${vitrine}/sites`);

  // Each site is a link to its page.
  await galerieSites.getByRole("link", { name: "Photos", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/site/\\?app=${galerie}&site=${photos.site.id}$`));
  await expect(page.getByRole("heading", { name: "Photos", level: 1 })).toBeVisible();

  // Older bookmarks: the main site of that nginx.
  const host = await (await page.request.get(`/api/v1/apps/${vitrine}/sites`)).json();
  const main = host.sites.find((s: { main: boolean }) => s.main).id;
  await page.goto(`/site/?id=${vitrine}`);
  await expect(page).toHaveURL(new RegExp(`/app/site/\\?app=${vitrine}&site=${main}$`));
  await expect(page.getByRole("heading", { name: "Vitrine", level: 1 })).toBeVisible();
  await expect(page.getByText("Site principal")).toBeVisible();
  expect(missing).toEqual([]);
});
