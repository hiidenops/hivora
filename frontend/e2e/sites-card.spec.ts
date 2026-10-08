import { existsSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { adminApi, deployNginx, expectPointerCursors, signIn, signInViewer } from "./helpers";

// The Sites card of an nginx's page: hosting, adding, switching, port, domain name, removal.

// The app -> sites model on the nginx app's page: host sites, add one after its preview
// (the restart is announced), turn it off; an nginx on template 1.0.0; a viewer.
test("nginx sites card: host sites, add one, turn it off, 1.0.0 and viewer", async ({ page, browser }) => {
  await signIn(page);

  // An nginx from the catalog serves one site.
  await page.getByRole("link", { name: "Catalogue", exact: true }).click(); // the menu (an empty dashboard has another)
  // Not anchored: until the catalog's icons are downloaded, their letters come first.
  await page.getByRole("link", { name: /Applications/ }).click();
  await page.getByRole("article", { name: "nginx" }).getByRole("link", { name: "Déployer" }).click();
  await page.getByLabel("Port web", { exact: true }).fill("8300");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Application en ligne" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await expect(page).toHaveURL(/\/app\/\?id=\d+$/);
  const appId = new URL(page.url()).searchParams.get("id");
  await expect(page.getByText("Ce nginx sert un seul site", { exact: false })).toBeVisible();

  // It hosts sites: its main site is listed, then a site is added after its preview.
  await page.getByRole("button", { name: "Héberger des sites" }).click();
  const sites = page.getByRole("list", { name: "Sites" });
  await expect(sites.getByText("Site principal")).toBeVisible();
  await expect(sites.getByText("Port 8300")).toBeVisible();
  await page.getByRole("button", { name: "Ajouter un site" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill("Blog");
  await dialog.getByLabel("Port", { exact: true }).fill("8301");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("tous ses sites seront indisponibles un court instant", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Ajouter le site" }).click();

  // Straight to the new site's page: empty, its content invited, its configuration followed;
  // the Sites menu entry is the current one, the site's own controls are here too.
  await expect(page).toHaveURL(/\/app\/site\/\?app=\d+&site=\d+&job=\d+$/);
  await expect(page.getByRole("heading", { name: "Blog", level: 1 })).toBeVisible();
  await expect(page.getByText("Ce site est vide", { exact: false })).toBeVisible();
  await expect(page.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("complementary").getByRole("link", { name: "Sites", exact: true })).toHaveClass(/font-medium/);
  await expect(page.getByRole("switch", { name: "Site « Blog » actif" })).toBeChecked();
  await expect(page.getByRole("button", { name: "Actions du site « Blog »" })).toBeVisible();
  await page.getByRole("navigation", { name: "Fil d'Ariane" }).getByRole("link").last().click(); // the nginx
  const blog = sites.getByRole("listitem", { name: "Blog" });
  await expect(blog.getByText("Port 8301")).toBeVisible({ timeout: 20_000 });

  // Its page through its Configure button (the name links there too).
  await blog.getByRole("link", { name: "Configurer le site « Blog »" }).click();
  await expect(page.getByRole("heading", { name: "Blog", level: 1 })).toBeVisible();
  await page.goBack();
  await expect(blog.getByText("Port 8301")).toBeVisible();

  // Its own switch: no restart notice, only this site.
  const toggle = blog.getByRole("switch", { name: "Site « Blog » actif" });
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked({ timeout: 20_000 });
  await expect(blog.getByText("Désactivé", { exact: true })).toBeVisible();
  await expect(page.getByText("tous ses sites seront indisponibles", { exact: false })).toHaveCount(0);
  await expectPointerCursors(page);

  // A stopped nginx: no site added (its revision would start it), each switch still works.
  await page.getByRole("button", { name: "Arrêter", exact: true }).click();
  await expect(page.getByText("Ce nginx est arrêté", { exact: false })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Ajouter un site" })).toBeDisabled();
  await expect(toggle).toBeEnabled();
  await page.getByRole("button", { name: "Actions du site « Blog »" }).click();
  await expect(page.getByRole("menuitem", { name: "Changer le port" })).toBeDisabled();
  await expect(page.getByRole("menuitem", { name: "Supprimer" })).toBeDisabled();
  await page.keyboard.press("Escape");

  // An nginx still on template 1.0.0 (answer replaced): told to update, nothing to add or switch.
  await page.route(`**/api/v1/apps/${appId}/sites`, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), upgrade_required: true } });
  });
  await page.reload();
  await expect(page.getByText("doit être mis à jour (version 1.1.0)", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ajouter un site" })).toBeDisabled();
  await expect(page.getByRole("switch", { name: "Site « Blog » actif" })).toBeDisabled();
  await page.unroute(`**/api/v1/apps/${appId}/sites`);

  // nginx refused its last configuration (answer replaced): said, with nginx's words, and
  // applied again on request.
  await page.route(`**/api/v1/apps/${appId}/sites`, async (route) => {
    const response = await route.fetch();
    const host = await response.json();
    const config = { ...host.config, status: "failed", error: "nginx refused the configuration: [emerg] boom" };
    await route.fulfill({ response, json: { ...host, config } });
  });
  await page.reload();
  await expect(page.getByText("La dernière configuration de nginx a échoué", { exact: false })).toBeVisible();
  await expect(page.getByText("[emerg] boom", { exact: false })).toBeVisible();
  const reapplied = page.waitForResponse((r) => r.url().endsWith(`/apps/${appId}/sites/config`));
  await page.getByRole("button", { name: "Réappliquer la configuration" }).click();
  expect((await reapplied).status()).toBe(202);
  await page.unroute(`**/api/v1/apps/${appId}/sites`);

  // A viewer sees the sites, changes nothing.
  const viewer = await signInViewer(page, browser, "valerie");
  await viewer.goto(`/app/?id=${appId}`);
  await expect(viewer.getByRole("list", { name: "Sites" }).getByRole("listitem")).toHaveCount(2);
  await expect(viewer.getByRole("button", { name: "Ajouter un site" })).toHaveCount(0);
  await expect(viewer.getByRole("switch", { name: "Site « Blog » actif" })).toBeDisabled();
  await expect(viewer.getByRole("button", { name: /^Actions du site/ })).toHaveCount(0); // no port, name or removal
  await expect(viewer.getByRole("link", { name: "Voir la configuration du site « Blog »" })).toBeVisible(); // not "Configure"
  await expect(viewer.getByRole("link", { name: /^Configurer le site/ })).toHaveCount(0);
  await viewer.close();
});

// An added site's menu on the nginx app's page: its port (conflict, suggested port, restart
// notice, compose diff in advanced mode), its domain name (advanced mode only), its removal
// with or without its files. The main site has no menu.
test("nginx sites card: change a port, a domain name, remove a site", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);

  // A host with two added sites, each with a file (set up through the API).
  const created = await deployNginx(page, "Pages", 8310);
  const app = created.app.id;
  expect((await page.request.post(`/api/v1/apps/${app}/sites/hosting`, { headers })).status()).toBe(200);
  for (const [name, port] of [["Blog", 8311], ["Wiki", 8312]] as const) {
    const change = await (await page.request.post(`/api/v1/apps/${app}/sites`, { headers, data: { name, port } })).json();
    await done(change.config_job.id);
    const saved = await page.request.put(`/api/v1/apps/${app}/sites/${change.site.id}/files/content`, {
      headers, data: { path: "index.html", content: `<h1>${name}</h1>`, base_sha256: null },
    }); // prettier-ignore
    await done((await saved.json()).id);
  }
  await deployNginx(page, "Voisin", 8315); // a neighbour nginx
  const folder = (slug: string) => `/tmp/hivora-e2e/srv/pages/sites/${slug}/index.html`;
  expect([existsSync(folder("blog")), existsSync(folder("wiki"))]).toEqual([true, true]);

  await page.goto(`/app/?id=${app}`);
  const sites = page.getByRole("list", { name: "Sites" });
  const blog = sites.getByRole("listitem", { name: "Blog" });
  await expect(blog.getByText("Port 8311")).toBeVisible();
  const menu = async (site: string, item: string) => {
    await page.getByRole("button", { name: `Actions du site « ${site} »` }).click();
    await page.getByRole("menuitem", { name: item }).click();
  };

  // Simple mode: no domain name in the menu; the main site's has its port only.
  await page.getByRole("button", { name: "Actions du site « Blog »" }).click();
  await expect(page.getByRole("menuitem")).toHaveText(["Changer le port", "Supprimer"]);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Actions du site « Pages »" }).click();
  await expect(page.getByRole("menuitem")).toHaveText(["Changer le port"]);
  await page.keyboard.press("Escape");

  // Port: Wiki's port is taken, and so is the neighbour nginx's: each time a really free one
  // is suggested (never one of this nginx's); then the restart is announced.
  await menu("Blog", "Changer le port");
  const dialog = page.getByRole("dialog");
  const newPort = dialog.getByLabel("Nouveau port", { exact: true });
  await expect(newPort).toHaveValue("8311");
  await newPort.fill("8312");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("Le port 8312/tcp est déjà utilisé par site wiki", { exact: false })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Utiliser le port 8313" })).toBeVisible();
  await newPort.fill("8315");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("Le port 8315/tcp est déjà utilisé par voisin", { exact: false })).toBeVisible();
  const port = "8316";
  await dialog.getByRole("button", { name: `Utiliser le port ${port}` }).click();
  await expect(newPort).toHaveValue(port);
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("pour publier ce port : tous ses sites seront indisponibles", { exact: false })).toBeVisible();
  await expect(dialog.locator("pre")).toHaveCount(0); // the compose diff: advanced mode only
  await dialog.getByRole("button", { name: "Changer le port" }).click();
  await expect(dialog).toBeHidden();
  await expect(blog.getByText(`Port ${port}`)).toBeVisible({ timeout: 20_000 });

  // The main site's port (the nginx's web port), from its port button this time.
  const main = sites.getByRole("listitem", { name: "Pages" });
  await main.getByRole("button", { name: "Port 8310 du site « Pages » : changer" }).click();
  await expect(newPort).toHaveValue("8310");
  await newPort.fill("8318");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("tous ses sites seront indisponibles", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Changer le port" }).click();
  await expect(dialog).toBeHidden();
  await expect(main.getByText("Port 8318")).toBeVisible({ timeout: 20_000 });
  expect((await (await page.request.get(`/api/v1/apps/${app}/settings`)).json()).values.web_port).toBe(8318);

  // Advanced mode: the compose diff before a port change, the domain name.
  await page.getByText("Mode avancé", { exact: true }).click();
  await menu("Wiki", "Changer le port");
  await newPort.fill("8319");
  await dialog.getByRole("button", { name: "Vérifier" }).click();
  await expect(dialog.getByText("tous ses sites seront indisponibles", { exact: false })).toBeVisible();
  await expect(dialog.locator("pre")).toContainText("8319"); // the compose diff
  await page.keyboard.press("Escape"); // nothing changed
  await expect(dialog).toBeHidden();
  await expect(sites.getByRole("listitem", { name: "Wiki" }).getByText("Port 8312")).toBeVisible();

  await menu("Blog", "Nom de domaine");
  await expect(dialog.getByText("aucun site n'est coupé", { exact: false })).toBeVisible();
  await dialog.getByLabel("Nom de domaine", { exact: true }).fill("blog;x");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible(); // invalid_site_config
  await dialog.getByLabel("Nom de domaine", { exact: true }).fill("blog.example.com");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog).toBeHidden();
  await expect(blog.getByText("blog.example.com")).toBeVisible({ timeout: 20_000 });

  // Removal, files kept (the default), then removal with its files.
  const remove = async (site: string, withData: boolean) => {
    await menu(site, "Supprimer");
    await expect(dialog.getByText("Son port", { exact: false })).toBeVisible();
    await expect(dialog.getByText("pour retirer ce port", { exact: false })).toBeVisible();
    const data = dialog.getByRole("switch", { name: "Supprimer aussi ses fichiers" });
    await expect(data).not.toBeChecked();
    await expect(dialog.getByText(`sites/${site.toLowerCase()}`)).toBeVisible();
    if (!withData) await expect(dialog.getByText("retrouvera ces fichiers", { exact: false })).toBeVisible();
    if (withData) {
      await data.click();
      await expect(dialog.getByText("Irréversible", { exact: false })).toBeVisible();
    }
    const sent = page.waitForResponse((r) => r.request().method() === "DELETE");
    await dialog.getByRole("button", { name: "Supprimer", exact: true }).click();
    const response = await sent;
    expect(new URL(response.url()).searchParams.get("remove_data")).toBe(String(withData));
    await done((await response.json()).job.id);
    await expect(dialog).toBeHidden();
    await expect(sites.getByRole("listitem", { name: site })).toHaveCount(0);
  };
  await remove("Wiki", false);
  expect(existsSync(folder("wiki"))).toBe(true);
  await remove("Blog", true);
  expect(existsSync(folder("blog"))).toBe(false);
  await expect(sites.getByRole("listitem")).toHaveCount(1); // the main site stays
  await expectPointerCursors(page);
});
