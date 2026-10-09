import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// Apache (the httpd template) hosts sites like nginx: hosting turned on from its card, a site
// added from the card, and its Apache virtual host written on disk.
test("apache hosts sites: turned on, a site added, its virtual host written", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "httpd", name: "Atelier Apache", inputs: { web_port: 8361 } },
  })).json(); // prettier-ignore
  await done(created.job.id);

  await page.goto("/sites/");
  await expect(page.getByRole("link", { name: "Nouvel Apache" }).first()).toHaveAttribute("href", "/deploy/?template=httpd");
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("link", { name: "Atelier Apache", exact: true }) });
  await expect(card.getByText("Ce serveur Apache sert un seul site, celui du volume « htdocs »", { exact: false })).toBeVisible();
  await card.getByRole("button", { name: "Héberger des sites" }).click();
  const sites = page.getByRole("list", { name: "Atelier Apache" });
  await expect(sites.getByText("Site principal")).toBeVisible();

  await card.getByRole("button", { name: "Ajouter un site" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill("Blog");
  await dialog.getByLabel("Port", { exact: true }).fill("8362");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("Ce serveur Apache va redémarrer", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Ajouter le site" }).click();
  await expect(page.getByRole("heading", { name: "Blog", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Suivi des tâches" }).getByText("Réussi").first()).toBeVisible({ timeout: 20_000 });

  const conf = () => readFileSync("/tmp/hivora-e2e/srv/atelier-apache/conf/site-blog.conf", "utf8");
  await expect.poll(conf, { timeout: 20_000 }).toContain("Listen 8362");
  expect(conf()).toContain("<VirtualHost *:8362>");
  expect(conf()).toContain('DocumentRoot "/usr/local/apache2/sites/blog"');
});
