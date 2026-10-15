import { expect, test } from "@playwright/test";

import { signIn, signInViewer } from "./helpers";

// The panel's health in Settings (admins), the source code link (everyone, before login).
test("system: health for admins, source code for everyone", async ({ page, browser }) => {
  await page.goto("/login/");
  const source = page.getByRole("link", { name: /Code source \(AGPL-3\.0\)/ });
  await expect(source).toHaveAttribute("href", /^https:\/\/github\.com\/hiidenops\/hivora/);
  await expect(source).toHaveAttribute("target", "_blank");

  await signIn(page);
  await page.goto("/settings/");
  await expect(page.getByRole("heading", { name: "Santé du panel" })).toBeVisible();
  await expect(page.getByText("Mode d'accès :")).toBeVisible();
  await expect(page.getByText("Réseau local uniquement")).toBeVisible();
  for (const name of ["Base de données", "Espace disque", "Docker", "Tâches", "Exposition du panel"]) {
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(/Inconnue \(Hivora ne tourne pas dans son conteneur\)/)).toBeVisible(); // fake Docker
  await page.getByRole("button", { name: "Vérifier la base" }).click();
  await expect(page.getByText(/vérification : ok/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Code source/ })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "publié sur toutes les adresses" })).toHaveCount(0);
  // No panel backup yet: "needs a look", the dot on Settings.
  await expect(page.getByRole("img", { name: "Santé du panel : à vérifier" })).toBeVisible();

  const viewer = await signInViewer(page, browser, "system-viewer");
  await viewer.goto("/settings/");
  await expect(viewer.getByRole("heading", { name: "Système" })).toBeVisible();
  await expect(viewer.getByRole("heading", { name: "Santé du panel" })).toHaveCount(0);
  await expect(viewer.getByRole("img", { name: /Santé du panel/ })).toHaveCount(0); // no dot
});
