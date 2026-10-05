import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-battery";

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
  await page.getByRole("link", { name: /^Applications/ }).click();
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

  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();

  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const deployed = await (
    await page.request.post("/api/v1/apps", {
      headers: { "X-CSRF-Token": csrf_token },
      data: { template: "nginx", name: "Témoin", inputs: { web_port: 8096 } },
    })
  ).json();
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/jobs/${deployed.job.id}`)).json()).status)
    .toBe("succeeded");

  await page.goto(`/app/?id=${deployed.app.id}`);
  await page.getByRole("button", { name: "Supprimer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByText("Application introuvable.")).toBeHidden();
});

test("sites: create a site, then turn it off and on", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();

  await page.getByRole("link", { name: "Sites" }).click();
  await expect(page.getByRole("heading", { name: "Sites" })).toBeVisible();
  await expect(page.getByText("Aucun site pour l'instant.")).toBeVisible();
  await expectPointerCursors(page);
  await page.getByRole("button", { name: "Nouveau site" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill("Vitrine");
  await dialog.getByLabel("Port", { exact: true }).fill("8095");
  await dialog.getByRole("button", { name: "Nouveau site" }).click();
  await expect(dialog).toBeHidden();

  // Two jobs: the deploy, then the first page.
  await expect(page.getByText("Contenu du site")).toBeVisible();
  await expect(page.getByText("Réussi")).toHaveCount(2, { timeout: 20_000 });
  const card = page.getByRole("article", { name: "Vitrine" });
  await expect(card.getByText("Port 8095")).toBeVisible();
  await expect(card.getByText("Sain")).toBeVisible({ timeout: 10_000 });

  const toggle = card.getByRole("switch", { name: "Site « Vitrine » actif" });
  await expect(toggle).toBeEnabled();
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await expect(card.getByText("Désactivé")).toBeVisible();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await expect(card.getByText("Actif")).toBeVisible();
  await expectPointerCursors(page);
  await expect(card.getByRole("link", { name: "Réglages de l'application" })).toHaveAttribute("href", /\/app\/\?id=\d+/);
});

test("sites: site page, open link, replace the content from a zip", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();

  await page.getByRole("link", { name: "Sites" }).click();
  await page.getByRole("article", { name: "Vitrine" }).getByRole("link", { name: "Vitrine" }).click();
  await expect(page).toHaveURL(/\/site\/\?id=\d+$/);
  await expect(page.getByRole("heading", { name: "Vitrine" })).toBeVisible();
  await expect(page.getByText("Port 8095")).toBeVisible();
  await expect(page.getByRole("switch", { name: "Site « Vitrine » actif" })).toBeChecked();
  await expect(page.getByRole("link", { name: "Ouvrir le site" })).toHaveAttribute("href", /^http:\/\/[\d.]+:8095$/);
  await expect(page.getByRole("link", { name: "Ouvrir le site" })).toHaveAttribute("target", "_blank");
  await expect(page.getByRole("link", { name: "Réglages de l'application" })).toHaveAttribute("href", /\/app\/\?id=\d+/);

  const replace = page.getByRole("button", { name: "Remplacer le contenu" });
  await expect(replace).toBeDisabled();
  await page.getByLabel("Archive .zip du site").setInputFiles(path.join(__dirname, "fixtures", "site.zip"));
  page.once("dialog", (dialog) => void dialog.accept());
  await replace.click();
  await expect(page.getByText("Contenu du site")).toBeVisible();
  await expect(page.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await expectPointerCursors(page);

  // The single top folder of the archive is removed: its files are at the site's root.
  const id = new URL(page.url()).searchParams.get("id");
  const files = await (await page.request.get(`/api/v1/sites/${id}/files`)).json();
  expect(files.files.map((f: { path: string }) => f.path)).toEqual(["css/site.css", "index.html"]);
  const index = await (await page.request.get(`/api/v1/sites/${id}/files/content?path=index.html`)).json();
  expect(index.content).toContain("Depuis le ZIP");
});

test("sites: read, edit, create a file, conflicts, and read only for viewers", async ({ page, browser }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
  await page.getByRole("link", { name: "Sites" }).click();
  await page.getByRole("article", { name: "Vitrine" }).getByRole("link", { name: "Vitrine" }).click();
  await expect(page).toHaveURL(/\/site\/\?id=\d+$/);
  const id = new URL(page.url()).searchParams.get("id");
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };

  // The files of the zip sent before; pick one, read it.
  const list = page.getByRole("list", { name: "Fichiers" });
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/]);
  await expect(page.getByText("Choisissez un fichier pour l'afficher.")).toBeVisible();
  await list.getByRole("button", { name: /index\.html/ }).click();
  const editor = page.getByLabel("Contenu de index.html");
  await expect(editor).toHaveValue(/Depuis le ZIP/);
  const save = page.getByRole("button", { name: "Enregistrer" });
  await expect(save).toBeDisabled(); // nothing changed yet

  // Edit and save: the job replaces the file, the editor takes the saved version.
  await editor.fill("<h1>Bienvenue</h1>\n");
  await expect(page.getByText("Modifications non enregistrées")).toBeVisible();
  await save.click();
  await expect(page.getByText("Enregistrement d'un fichier")).toBeVisible();
  await expect(page.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Modifications non enregistrées")).toBeHidden();
  await expect(save).toBeDisabled();

  // Someone else saves the same file meanwhile: refused, then reloaded on request.
  await editor.fill("<h1>Ma version</h1>\n");
  const read = await (await page.request.get(`/api/v1/sites/${id}/files/content?path=index.html`)).json();
  const other = await (await page.request.put(`/api/v1/sites/${id}/files/content`, {
    headers, data: { path: "index.html", content: "<h1>Leur version</h1>\n", base_sha256: read.sha256 },
  })).json(); // prettier-ignore
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/jobs/${other.id}`)).json()).status)
    .toBe("succeeded");
  await expect(editor).toHaveValue("<h1>Ma version</h1>\n"); // the draft is kept
  await save.click();
  await expect(page.getByText("Le fichier a changé depuis son ouverture.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Recharger" }).click();
  await expect(editor).toHaveValue("<h1>Leur version</h1>\n");

  // A new file in a new folder; a file type that cannot be edited is refused.
  await page.getByLabel("Nouveau fichier").fill("notes.txt");
  await page.getByRole("button", { name: "Créer" }).click();
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Seuls les fichiers .html, .css et .js peuvent être modifiés.")).toBeVisible();
  await page.getByLabel("Nouveau fichier").fill("js/app.js");
  await page.getByRole("button", { name: "Créer" }).click();
  await expect(page.getByText("Nouveau fichier : il sera créé à l'enregistrement.")).toBeVisible();
  await page.getByLabel("Contenu de js/app.js").fill("console.log('ok');\n");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/, /js\/app\.js/], { timeout: 20_000 });
  await expectPointerCursors(page);

  // A viewer reads the same page: no upload, no save, no new file, no switch.
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
  await viewer.goto(`/site/?id=${id}`);
  await viewer.getByRole("list", { name: "Fichiers" }).getByRole("button", { name: /js\/app\.js/ }).click();
  const readOnly = viewer.getByLabel("Contenu de js/app.js");
  await expect(readOnly).toHaveValue("console.log('ok');\n");
  await expect(readOnly).toHaveAttribute("readonly", "");
  await expect(viewer.getByText("Lecture seule")).toBeVisible();
  await expect(viewer.getByRole("button", { name: "Enregistrer" })).toHaveCount(0);
  await expect(viewer.getByLabel("Nouveau fichier")).toHaveCount(0);
  await expect(viewer.getByRole("button", { name: "Remplacer le contenu" })).toHaveCount(0);
  await expect(viewer.getByRole("switch", { name: "Site « Vitrine » actif" })).toBeDisabled();
  await viewer.close();
});

// The app -> sites model through the API only (no screen yet): a host, an added site on
// its own port, then off and removed. The older /sites routes keep working beside it.
test("hosted sites API: list, plan, add, edit a file, turn off, remove", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");

  const created = await (await page.request.post("/api/v1/sites", { headers, data: { name: "Annexe", port: 8200 } })).json();
  await done(created.job.id);
  await done(created.content_job.id);
  const app = created.site.id;
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
  // The older model still answers for the same host.
  const old = await (await page.request.get("/api/v1/sites")).json();
  expect(old.map((s: { slug: string }) => s.slug)).toContain("annexe");
});
