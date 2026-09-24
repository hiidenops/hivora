import { expect, test } from "@playwright/test";

const PASSWORD = "correct-horse-battery";

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

  // Catalog -> deploy wizard -> review (compose shown, secrets referenced) -> deploy.
  await page.getByRole("link", { name: "Parcourir le catalogue" }).click();
  await page.getByRole("article", { name: "Vaultwarden" }).getByRole("link", { name: "Déployer" }).click();
  await expect(page.getByRole("heading", { name: "Déployer Vaultwarden" })).toBeVisible();
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Fichier compose généré")).toBeVisible();
  await expect(page.locator("pre").first()).toContainText("${HV_SECRET_ADMIN_TOKEN:-}");
  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Application en ligne" })).toBeVisible({ timeout: 20_000 });

  // App page, then removal: data kept unless explicitly checked.
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await expect(page.getByRole("heading", { name: /Vaultwarden/ })).toBeVisible();
  expect(await page.evaluate(() => isSecureContext)).toBe(false); // the realistic case
  await expect(page.getByRole("heading", { name: "Console" })).toBeVisible();
  await expect(page.locator(".xterm")).toBeVisible(); // auto-connected on a running app
  await expect(page.locator(".xterm-rows")).toContainText("$ sh -c"); // fake exec echoes its command
  await page.getByRole("button", { name: "Supprimer" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("switch", { name: "Aussi supprimer les données" })).not.toBeChecked();
  await dialog.getByRole("button", { name: "Supprimer" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByText("Aucune application pour l'instant.")).toBeVisible();

  // User management (admin only).
  await page.getByRole("link", { name: "Utilisateurs" }).click();
  await page.getByRole("button", { name: "Ajouter un utilisateur" }).click();
  await page.getByLabel("Identifiant", { exact: true }).fill("lea");
  await page.getByLabel("Rôle", { exact: true }).selectOption("operator");
  await page.getByLabel("Mot de passe temporaire", { exact: true }).fill("temporary-pass-1");
  await page.getByRole("dialog").getByRole("button", { name: "Ajouter un utilisateur" }).click();
  await expect(page.getByRole("button", { name: "Actions pour lea" })).toBeVisible();

  // Language switch.
  await page.getByRole("link", { name: "Paramètres" }).click();
  await page.getByLabel("Langue", { exact: true }).selectOption("en");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});
