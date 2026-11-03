import { expect, test } from "./test";

import { signIn, signInViewer } from "./helpers";

// System → Updates: GitHub Releases as e2e_app fakes them (v9.1.0 stable, v9.2.0-rc.1).
test("releases: the newer version, its notes and command, the channel", async ({ page, browser }) => {
  await signIn(page);
  // The System button at the bottom of the navigation; every navigation click asks the
  // server for the available version again.
  await page.goto("/");
  const asked = page.waitForRequest((r) => r.url().endsWith("/api/v1/system/releases") && r.method() === "GET");
  await page.getByRole("link", { name: "Système" }).first().click();
  await asked;
  await expect(page).toHaveURL(/\/system\/$/);
  const card = page; // the texts below are the Updates card's own
  await expect(card.getByRole("heading", { name: "Mises à jour" })).toBeVisible();
  await expect(card.getByText("Canal :").first()).toBeVisible();
  await expect(card.getByText("Stable", { exact: true }).first()).toBeVisible();
  await expect(card.getByText("Nouvelle version 9.1.0 disponible")).toBeVisible();
  await expect(card.getByRole("link", { name: "Voir la release" })).toHaveAttribute("href", /releases\/tag\/v9\.1\.0$/);
  await card.getByRole("button", { name: "Notes de la version 9.1.0" }).click();
  const notes = page.getByRole("dialog", { name: "Notes de la version 9.1.0" });
  await expect(notes.getByRole("listitem")).toHaveText("Tout ce qui manquait."); // Markdown, not "- …"
  await expect(notes.getByText("Ajouté", { exact: true })).toBeVisible(); // "### " gone
  await notes.getByRole("button", { name: "Fermer" }).last().click();
  await expect(notes).toBeHidden();
  await expect(card.getByText('sudo sh -c "$(curl -fsSL https://github.com/hiidenops/hivora/releases/download/v9.1.0/install.sh)"')).toBeVisible();
  await card.getByRole("button", { name: "Copier" }).click();
  await expect(card.getByRole("button", { name: "Copié" })).toBeVisible();
  // Health first: with the panel backup missing the dot is orange; the update is in the card.
  await expect(page.getByRole("img", { name: /Santé du panel|Nouvelle version/ })).toHaveCount(1);

  // Pre-releases: the candidate.
  await card.getByLabel("Canal :").selectOption("pre");
  await expect(card.getByText("Nouvelle version 9.2.0-rc.1 disponible")).toBeVisible();
  await expect(card.getByText("Pré-versions", { exact: true }).first()).toBeVisible();

  // Off: nothing known, nothing asked.
  await card.getByRole("switch", { name: "Vérifier automatiquement les nouvelles versions" }).click();
  await expect(card.getByText("Vérification des nouvelles versions désactivée.")).toBeVisible();
  await expect(card.getByRole("button", { name: "Vérifier maintenant" })).toHaveCount(0);
  await card.getByRole("switch", { name: "Vérifier automatiquement les nouvelles versions" }).click();
  await card.getByLabel("Canal :").selectOption("stable"); // as other tests expect it

  const viewer = await signInViewer(page, browser, "releases-viewer");
  await viewer.goto("/system/");
  await expect(viewer.getByRole("heading", { name: "Système" }).first()).toBeVisible();
  await expect(viewer.getByRole("heading", { name: "Mises à jour" })).toHaveCount(0);
});
