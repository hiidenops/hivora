import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-battery";

/** Signed in as admin, whatever ran before: the forced first password change is done here
 *  through the API if no earlier test did it (each test can run alone). */
async function signIn(page: Page) {
  const login = (password: string) => page.request.post("/api/v1/auth/login", { data: { username: "admin", password } });
  if (!(await login(PASSWORD)).ok()) {
    const first = await login("admin");
    expect(first.ok()).toBe(true);
    const changed = await page.request.post("/api/v1/auth/password", {
      headers: { "X-CSRF-Token": (await first.json()).csrf_token },
      data: { current: "admin", new: PASSWORD },
    });
    expect(changed.ok()).toBe(true);
  }
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
}

/** Everything clickable on the page shows the hand (disabled controls excepted). */
async function expectPointerCursors(page: Page) {
  const arrows = await page.$$eval(
    "button:not(:disabled), a[href], select:not(:disabled), [role=tab], [role=switch]:not(:disabled), summary",
    (els) =>
      els
        .filter((e) => getComputedStyle(e).cursor !== "pointer")
        .map((e) => `${e.tagName} ${(e.textContent || e.getAttribute("aria-label") || "").trim().slice(0, 40)}`),
  );
  expect(arrows).toEqual([]);
}

test("first start: forced password change, deploy, remove, users", async ({ page }) => {
  // admin/admin, then the forced password change.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login\/$/);
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill("admin");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/change-password\/$/);
  await page.getByLabel("Mot de passe actuel", { exact: true }).fill("admin");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
  await expect(page.getByText("En direct")).toBeVisible();
  await expectPointerCursors(page);
  // Hovering the menu never makes it scroll (Windows shows real scrollbars).
  for (const link of await page.locator("aside nav a").all()) {
    await link.hover();
    const scrolls = await page.locator("aside, aside *").evaluateAll((els) =>
      els.filter((e) => {
        const s = getComputedStyle(e);
        return (e.scrollWidth > e.clientWidth && ["auto", "scroll"].includes(s.overflowX)) ||
          (e.scrollHeight > e.clientHeight && ["auto", "scroll"].includes(s.overflowY));
      }).length,
    );
    expect(scrolls).toBe(0);
  }

  // Catalog -> deploy wizard -> review (compose shown, secrets referenced) -> deploy.
  await page.getByRole("link", { name: "Parcourir le catalogue" }).click();
  // Not anchored: until the catalog's icons are downloaded, their letters come first.
  await page.getByRole("link", { name: /Applications/ }).click();
  await page.getByRole("article", { name: "Vaultwarden" }).getByRole("link", { name: "Déployer" }).click();
  await expect(page.getByRole("heading", { name: "Déployer Vaultwarden" })).toBeVisible();
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Fichier compose généré")).toBeVisible();
  await expectPointerCursors(page);
  await expect(page.locator("pre").first()).toContainText("${HV_SECRET_ADMIN_TOKEN:-}");
  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Application en ligne" })).toBeVisible({ timeout: 20_000 });

  // App page, then removal: data kept unless explicitly checked.
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await expect(page.getByRole("heading", { name: /Vaultwarden/ })).toBeVisible();
  expect(await page.evaluate(() => isSecureContext)).toBe(false); // the realistic case
  await expect(page.getByRole("button", { name: "Console", expanded: true })).toBeVisible();
  // Live usage: sampled every 5 s only while the page is open.
  await expect(page.getByRole("region", { name: "Consommation" })).toContainText("25,0 %", { timeout: 12_000 });
  await expect(page.locator(".xterm")).toBeVisible(); // auto-connected on a running app
  await page.locator(".xterm").scrollIntoViewIfNeeded(); // xterm only paints on screen
  await expectPointerCursors(page);
  await expect(page.locator(".xterm-rows")).toContainText("$ sh -c"); // fake exec echoes its command
  await page.getByRole("button", { name: "Supprimer" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("switch", { name: "Aussi supprimer les données" })).not.toBeChecked();
  await dialog.getByRole("button", { name: "Supprimer" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByText("Aucune application pour l'instant.")).toBeVisible();

  // Changing a flagged setting (server type) erases the data: confirmed explicitly.
  await page.getByRole("link", { name: "Parcourir le catalogue" }).click();
  // The catalog page itself, not the dashboard's link caught mid-navigation.
  await expect(page).toHaveURL(/\/catalog\/$/);
  await expect(page.getByRole("link", { name: /^Jeux/ })).toBeVisible();
  await expectPointerCursors(page);
  await page.getByRole("link", { name: /^Jeux/ }).click();
  await page.getByRole("article", { name: "Minecraft Java" }).getByRole("link", { name: "Déployer" }).click();
  await page.getByRole("switch", { name: /J'accepte le contrat de licence Minecraft/ }).check();
  await page.getByRole("button", { name: "Vérifier" }).click();
  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Application en ligne" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await page.getByRole("link", { name: "Modifier" }).click();
  await page.getByLabel("Type de serveur", { exact: true }).selectOption("PAPER");
  await expectPointerCursors(page);
  await page.getByRole("button", { name: "Vérifier les changements" }).click();
  await expect(page.getByText(/Changer « Type de serveur » efface tout le contenu du serveur/)).toBeVisible();
  const erase = page.getByRole("button", { name: "Effacer et appliquer" });
  await expect(erase).toBeDisabled();
  await page.getByRole("switch", { name: "J'ai compris, tout effacer et appliquer" }).check();
  await erase.click();
  await expect(page.getByRole("heading", { name: "Réglages appliqués" })).toBeVisible({ timeout: 20_000 });

  // User management (admin only).
  await page.getByRole("link", { name: "Utilisateurs" }).click();
  await page.getByRole("button", { name: "Ajouter un utilisateur" }).click();
  await page.getByLabel("Identifiant", { exact: true }).fill("lea");
  await page.getByLabel("Rôle", { exact: true }).selectOption("operator");
  await page.getByLabel("Mot de passe temporaire", { exact: true }).fill("temporary-pass-1");
  await page.getByRole("dialog").getByRole("button", { name: "Ajouter un utilisateur" }).click();
  await expect(page.getByRole("button", { name: "Actions pour lea" })).toBeVisible();
  await page.getByRole("button", { name: "Actions pour lea" }).click();
  await expect(page.getByRole("menuitem", { name: "Réinitialiser le mot de passe" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toBeHidden();

  // Host firewall page: the agent is off by default, nothing runs on the host.
  await page.getByRole("link", { name: "Pare-feu" }).click();
  await expect(page.getByRole("heading", { name: "Pare-feu" })).toBeVisible();
  await expect(page.getByText("UFW ne filtre pas les ports publiés par Docker", { exact: false }).first()).toBeVisible();

  // Language switch.
  await page.getByRole("link", { name: "Paramètres" }).click();
  await page.getByLabel("Langue", { exact: true }).selectOption("en");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});

// Regression: removal deletes the app before its job ends. If the page sees the 404 first,
// it must still go back to the dashboard. Made deterministic by hiding the end of the job
// from the page: its WebSocket event is dropped and its REST record shows it running.
test("removal goes back to the dashboard even if the app is gone before its job ends", async ({ page }) => {
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((message) => server.send(message));
    server.onMessage((message) => {
      const msg = typeof message === "string" ? JSON.parse(message) : null;
      if (msg?.channel === "jobs" && msg.type === "finished") return;
      ws.send(message);
    });
  });
  await page.route(/\/api\/v1\/jobs\/\d+$/, async (route) => {
    const response = await route.fetch();
    const job = await response.json();
    const hidden = job.kind === "remove" ? { ...job, status: "running", finished_at: null } : job;
    await route.fulfill({ response, json: hidden });
  });

  await signIn(page);

  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const deployed = await (
    await page.request.post("/api/v1/apps", {
      headers: { "X-CSRF-Token": csrf_token },
      data: { template: "nginx", name: "Témoin", inputs: { web_port: 8090 } },
    })
  ).json();
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/jobs/${deployed.job.id}`)).json()).status, {
      timeout: 20_000,
    })
    .toBe("succeeded");

  await page.goto(`/app/?id=${deployed.app.id}`);
  await page.getByRole("button", { name: "Supprimer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByText("Application introuvable.")).toBeHidden();
});

// The sites index (/sites): one Sites card per nginx, each site a link to its page; an nginx
// that hosts no sites yet offers to; older bookmarks (/site/?id=) reach the main site.
test("sites index: grouped by nginx, host sites, site links, older bookmarks", async ({ page }) => {
  await signIn(page);
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");

  // Asked only for the nginx that host sites: no expected 404 any more.
  const missing: string[] = [];
  page.on("response", (r) => {
    if (r.status() === 404 && r.url().includes("/api/v1/")) missing.push(r.url());
  });

  // No nginx yet (an earlier test's may still be going): the way to deploy one.
  await expect
    .poll(async () => (await (await page.request.get("/api/v1/apps")).json()).filter((a: { template: string }) => a.template === "nginx").length, {
      timeout: 20_000,
    })
    .toBe(0);
  await page.getByRole("link", { name: "Sites" }).click();
  await expect(page.getByRole("heading", { name: "Sites", level: 1 })).toBeVisible();
  await expect(page.getByText("Aucun nginx pour l'instant", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Nouveau nginx" }).first()).toHaveAttribute("href", "/deploy/?template=nginx");
  await expectPointerCursors(page);

  // Two nginx (through the API): Vitrine serves one site, Galerie hosts an added one.
  const nginx = async (name: string, port: number) => {
    const created = await (await page.request.post("/api/v1/apps", {
      headers, data: { template: "nginx", name, inputs: { web_port: port } },
    })).json(); // prettier-ignore
    await done(created.job.id);
    return created.app.id as number;
  };
  const vitrine = await nginx("Vitrine", 8095);
  const galerie = await nginx("Galerie", 8096);
  await page.request.post(`/api/v1/apps/${galerie}/sites/hosting`, { headers });
  const photos = await (await page.request.post(`/api/v1/apps/${galerie}/sites`, { headers, data: { name: "Photos", port: 8097 } })).json();
  await done(photos.config_job.id);

  await page.reload();
  const vitrineSites = page.getByRole("list", { name: "Vitrine" });
  const galerieSites = page.getByRole("list", { name: "Galerie" });
  await expect(galerieSites.getByRole("listitem")).toHaveText([/Galerie.*Site principal.*Port 8096/, /Photos.*Port 8097/]);
  await expect(page.getByRole("link", { name: "Galerie", exact: true }).first()).toHaveAttribute("href", `/app/?id=${galerie}`);
  await expect(vitrineSites).toHaveCount(0);
  await expect(page.getByText("Ce nginx sert un seul site", { exact: false })).toBeVisible();

  // Vitrine starts hosting from the index; its main site, off then on.
  await page.getByRole("button", { name: "Héberger des sites" }).click();
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

// The app -> sites model through the API only: an nginx from the catalog starts hosting,
// an added site on its own port, then off and removed.
test("hosted sites API: list, plan, add, edit a file, turn off, remove", async ({ page }) => {
  await signIn(page);
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");

  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Annexe", inputs: { web_port: 8200 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const app = created.app.id;
  const hosting = await page.request.post(`/api/v1/apps/${app}/sites/hosting`, { headers });
  expect(hosting.status()).toBe(200);
  const host = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(host.sites.map((s: { slug: string; main: boolean }) => [s.slug, s.main])).toEqual([["main", true]]);

  const site = { name: "Docs", port: 8201 };
  const plan = await (await page.request.post(`/api/v1/apps/${app}/sites/plan`, { headers, data: site })).json();
  expect([plan.recreate, plan.ports_after]).toEqual([true, [8201]]);
  const added = await page.request.post(`/api/v1/apps/${app}/sites`, { headers, data: site });
  expect(added.status()).toBe(202);
  const change = await added.json();
  expect([change.job.kind, change.config_job.kind]).toEqual(["update", "site_config"]);
  await done(change.job.id);
  await done(change.config_job.id);
  const listed = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(listed.sites.map((s: { slug: string; port: number }) => [s.slug, s.port])).toEqual([["main", 8200], ["docs", 8201]]);

  const docs = change.site.id;
  // The added site's own files: one created, then read back.
  const saved = await page.request.put(`/api/v1/apps/${app}/sites/${docs}/files/content`, {
    headers, data: { path: "index.html", content: "<h1>Docs</h1>", base_sha256: null },
  }); // prettier-ignore
  expect(saved.status()).toBe(202);
  await done((await saved.json()).id);
  const files = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/files`)).json();
  expect(files.files.map((f: { path: string }) => f.path)).toEqual(["index.html"]);
  const read = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/files/content?path=index.html`)).json();
  expect(read.content).toBe("<h1>Docs</h1>");
  const off = await page.request.put(`/api/v1/apps/${app}/sites/${docs}/enabled`, { headers, data: { enabled: false } });
  expect(off.status()).toBe(202);
  await done((await off.json()).id);
  const removal = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/removal-plan`)).json();
  expect(removal.ports_after).toEqual([]);
  const gone = await page.request.delete(`/api/v1/apps/${app}/sites/${docs}`, { headers });
  expect(gone.status()).toBe(202);
  await done((await gone.json()).job.id);
  const after = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(after.sites.map((s: { slug: string }) => s.slug)).toEqual(["main"]);
});

// The app -> sites model on the nginx app's page: host sites, add one after its preview
// (the restart is announced), turn it off; an nginx on template 1.0.0; a viewer.
test("nginx sites card: host sites, add one, turn it off, 1.0.0 and viewer", async ({ page, browser }) => {
  await signIn(page);

  // An nginx from the catalog serves one site.
  await page.getByRole("link", { name: "Catalogue" }).click();
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
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  await page.request.post("/api/v1/users", {
    headers: { "X-CSRF-Token": csrf_token },
    data: { username: "valerie", role: "viewer", password: "temporary-pass-1" },
  });
  const viewer = await browser.newPage();
  await viewer.goto("/login/");
  await viewer.getByLabel("Identifiant", { exact: true }).fill("valerie");
  await viewer.getByLabel("Mot de passe", { exact: true }).fill("temporary-pass-1");
  await viewer.getByRole("button", { name: "Se connecter" }).click();
  await viewer.getByLabel("Mot de passe actuel", { exact: true }).fill("temporary-pass-1");
  await viewer.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByRole("button", { name: "Enregistrer" }).click();
  await expect(viewer.getByRole("heading", { name: "Applications" })).toBeVisible();
  await viewer.goto(`/app/?id=${appId}`);
  await expect(viewer.getByRole("list", { name: "Sites" }).getByRole("listitem")).toHaveCount(2);
  await expect(viewer.getByRole("button", { name: "Ajouter un site" })).toHaveCount(0);
  await expect(viewer.getByRole("switch", { name: "Site « Blog » actif" })).toBeDisabled();
  await expect(viewer.getByRole("button", { name: /^Actions du site/ })).toHaveCount(0); // no port, name or removal
  await viewer.close();
});

// An added site's menu on the nginx app's page: its port (conflict, suggested port, restart
// notice, compose diff in advanced mode), its domain name (advanced mode only), its removal
// with or without its files. The main site has no menu.
test("nginx sites card: change a port, a domain name, remove a site", async ({ page }) => {
  await signIn(page);
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");

  // A host with two added sites, each with a file (set up through the API).
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Pages", inputs: { web_port: 8310 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
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
  const neighbour = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Voisin", inputs: { web_port: 8315 } },
  })).json(); // prettier-ignore
  await done(neighbour.job.id);
  const folder = (slug: string) => `/tmp/hivora-e2e/srv/pages/sites/${slug}/index.html`;
  expect([existsSync(folder("blog")), existsSync(folder("wiki"))]).toEqual([true, true]);

  await page.goto(`/app/?id=${app}`);
  const sites = page.getByRole("list", { name: "Sites" });
  const blog = sites.getByRole("listitem", { name: "Blog" });
  await expect(blog.getByText("Port 8311")).toBeVisible();
  await expect(page.getByRole("button", { name: "Actions du site « Pages »" })).toHaveCount(0); // the main site
  const menu = async (site: string, item: string) => {
    await page.getByRole("button", { name: `Actions du site « ${site} »` }).click();
    await page.getByRole("menuitem", { name: item }).click();
  };

  // Simple mode: no domain name in the menu.
  await page.getByRole("button", { name: "Actions du site « Blog »" }).click();
  await expect(page.getByRole("menuitem")).toHaveText(["Changer le port", "Supprimer"]);
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

// The page of one site an nginx hosts (/app/site/?app=&site=): the content and file cards
// on /apps/{app}/sites/{site}, never on the older /sites routes; the site's own folder only.
test("hosted site page: zip, read, create, edit, conflict, viewer, back to the nginx", async ({ page, browser }) => {
  await signIn(page);
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");

  // A host with one added site (set up through the API).
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Atelier", inputs: { web_port: 8320 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const app = created.app.id;
  expect((await page.request.post(`/api/v1/apps/${app}/sites/hosting`, { headers })).status()).toBe(200);
  const added = await (await page.request.post(`/api/v1/apps/${app}/sites`, { headers, data: { name: "Docs", port: 8321 } })).json();
  await done(added.config_job.id);
  const site = added.site.id;
  const base = `/api/v1/apps/${app}/sites/${site}`;
  const disk = "/tmp/hivora-e2e/srv/atelier";

  // Every request the page makes for content and files.
  const calls: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url()).pathname;
    if (/\/(content|files)/.test(url)) calls.push(`${r.method()} ${url}`);
  });

  await page.goto(`/app/site/?app=${app}&site=${site}`);
  const crumbs = page.getByRole("navigation", { name: "Fil d'Ariane" });
  await expect(crumbs).toHaveText(/Atelier.*Docs/);
  await expect(page.getByRole("heading", { name: "Docs", level: 1 })).toBeVisible();
  await expect(page.getByText("Port 8321")).toBeVisible();
  await expect(page.getByText("Actif", { exact: true })).toBeVisible();
  const open = page.getByRole("link", { name: "Ouvrir le site" });
  await expect(open).toHaveAttribute("href", /^http:\/\/[\d.]+:8321$/);
  await expect(open).toHaveAttribute("target", "_blank");
  await expect(page.getByText("Aucun fichier", { exact: false })).toBeVisible(); // a new site: empty folder
  await expect(crumbs.getByRole("link", { name: "Sites", exact: true })).toHaveAttribute("href", "/sites/");

  // An empty site: a first page in one click, titled with its name.
  await page.getByRole("button", { name: "Créer index.html" }).click();
  await expect(page.getByRole("list", { name: "Fichiers" }).getByRole("button")).toHaveText([/index\.html/], { timeout: 20_000 });
  await expect.poll(() => existsSync(`${disk}/sites/docs/index.html`)).toBe(true);
  expect(readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toContain("<h1>Docs</h1>");
  await expect(page.getByText("Ce site est vide", { exact: false })).toBeHidden();

  // A zip: in the site's own folder, the main site untouched.
  const mainTree = () => (existsSync(`${disk}/html`) ? readdirSync(`${disk}/html`, { recursive: true }).sort() : []);
  const mainBefore = mainTree();
  await page.getByLabel("Archive .zip du site").setInputFiles(path.join(__dirname, "fixtures", "site.zip"));
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Remplacer le contenu" }).click();
  await expect(page.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  const list = page.getByRole("list", { name: "Fichiers" });
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/], { timeout: 20_000 });
  expect(readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toContain("Depuis le ZIP");
  expect(mainTree()).toEqual(mainBefore);

  // Read, then edit and save.
  await list.getByRole("button", { name: /index\.html/ }).click();
  const editor = page.getByLabel("Contenu de index.html");
  await expect(editor).toHaveValue(/Depuis le ZIP/);
  const save = page.getByRole("button", { name: "Enregistrer" });
  await expect(save).toBeDisabled();
  await editor.fill("<h1>Docs</h1>\n");
  await save.click();
  await expect(page.getByText("Enregistrement d'un fichier")).toBeVisible();
  await expect(page.getByText("Modifications non enregistrées")).toBeHidden({ timeout: 20_000 });
  await expect.poll(() => readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toBe("<h1>Docs</h1>\n");

  // Saved meanwhile by someone else: file_changed, then reloaded on request.
  await editor.fill("<h1>Ma version</h1>\n");
  const read = await (await page.request.get(`${base}/files/content?path=index.html`)).json();
  const other = await (await page.request.put(`${base}/files/content`, {
    headers, data: { path: "index.html", content: "<h1>Leur version</h1>\n", base_sha256: read.sha256 },
  })).json(); // prettier-ignore
  await done(other.id);
  await save.click();
  await expect(page.getByText("Le fichier a changé depuis son ouverture.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Recharger" }).click();
  await expect(editor).toHaveValue("<h1>Leur version</h1>\n");

  // A new file in a new folder.
  await page.getByLabel("Nouveau fichier").fill("js/app.js");
  await page.getByRole("button", { name: "Créer" }).click();
  await page.getByLabel("Contenu de js/app.js").fill("console.log('docs');\n");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/, /js\/app\.js/], { timeout: 20_000 });
  expect(existsSync(`${disk}/sites/docs/js/app.js`)).toBe(true);
  expect(mainTree()).toEqual(mainBefore);
  await expectPointerCursors(page);

  // The page used the hosted site's routes only.
  expect(calls.length).toBeGreaterThan(0);
  expect(calls.filter((c) => !c.split(" ")[1].startsWith(`${base}/`))).toEqual([]);

  // Back to the nginx.
  await crumbs.getByRole("link", { name: "Atelier" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/\\?id=${app}$`));
  await expect(page.getByRole("list", { name: "Sites" }).getByRole("listitem", { name: "Docs" })).toBeVisible();

  // A viewer reads, writes nothing.
  await page.request.post("/api/v1/users", {
    headers, data: { username: "vera", role: "viewer", password: "temporary-pass-1" },
  }); // prettier-ignore
  const viewer = await browser.newPage();
  await viewer.goto("/login/");
  await viewer.getByLabel("Identifiant", { exact: true }).fill("vera");
  await viewer.getByLabel("Mot de passe", { exact: true }).fill("temporary-pass-1");
  await viewer.getByRole("button", { name: "Se connecter" }).click();
  await viewer.getByLabel("Mot de passe actuel", { exact: true }).fill("temporary-pass-1");
  await viewer.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByRole("button", { name: "Enregistrer" }).click();
  await expect(viewer.getByRole("heading", { name: "Applications" })).toBeVisible();
  await viewer.goto(`/app/site/?app=${app}&site=${site}`);
  await viewer.getByRole("list", { name: "Fichiers" }).getByRole("button", { name: /js\/app\.js/ }).click();
  const readOnly = viewer.getByLabel("Contenu de js/app.js");
  await expect(readOnly).toHaveValue("console.log('docs');\n");
  await expect(readOnly).toHaveAttribute("readonly", "");
  await expect(viewer.getByRole("button", { name: "Enregistrer" })).toHaveCount(0);
  await expect(viewer.getByLabel("Nouveau fichier")).toHaveCount(0);
  await expect(viewer.getByRole("button", { name: "Remplacer le contenu" })).toHaveCount(0);
  await viewer.close();
});
