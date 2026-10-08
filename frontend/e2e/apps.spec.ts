import { expect, test } from "@playwright/test";

import { PASSWORD, deployNginx, expectPointerCursors, openAppMenu, signIn } from "./helpers";

// The panel's first start and an app's removal.

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
  // Live usage: sampled every 5 s only while the page is open.
  await expect(page.getByRole("region", { name: "Consommation" })).toContainText("25,0 %", { timeout: 12_000 });
  await page.getByRole("button", { name: "Logs et console" }).click(); // its button: both side by side, wide panel
  const panel = page.getByRole("dialog", { name: "Logs et console" });
  await expect(panel.getByRole("region", { name: "Logs", exact: true })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Console", exact: true })).toBeVisible();
  await expect(page.locator(".xterm")).toBeVisible(); // auto-connected on a running app
  await page.locator(".xterm").scrollIntoViewIfNeeded(); // xterm only paints on screen
  await expectPointerCursors(page);
  await expect(page.locator(".xterm-rows")).toContainText("$ sh -c"); // fake exec echoes its command
  // The command line under the terminal: Enter sends it, the arrow brings it back.
  const line = panel.getByRole("textbox", { name: "Commande" });
  await line.fill("ls");
  await line.press("Enter");
  await expect(line).toHaveValue("");
  await line.press("ArrowUp");
  await expect(line).toHaveValue("ls");
  await page.keyboard.press("Escape"); // the panel closes
  await expect(panel).toBeHidden();
  await openAppMenu(page, "Supprimer");
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
  await openAppMenu(page, "Modifier");
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

  const deployed = await deployNginx(page, "Témoin", 8090);

  await page.goto(`/app/?id=${deployed.app.id}`);
  await openAppMenu(page, "Supprimer");
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByText("Application introuvable.")).toBeHidden();
});
