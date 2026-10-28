import { expect, test } from "@playwright/test";

import { signIn, signInViewer } from "./helpers";

// Settings → Updates: GitHub Releases as e2e_app fakes them (v9.1.0 stable, v9.2.0-rc.1).
test("releases: the newer version, its notes and command, the channel", async ({ page, browser }) => {
  await signIn(page);
  await page.goto("/settings/");
  const card = page; // the texts below are the Updates card's own
  await expect(card.getByRole("heading", { name: "Mises à jour" })).toBeVisible();
  await expect(card.getByText("Canal :").first()).toBeVisible();
  await expect(card.getByText("Stable", { exact: true }).first()).toBeVisible();
  await expect(card.getByText("Nouvelle version 9.1.0 disponible")).toBeVisible();
  await expect(card.getByRole("link", { name: "Voir la release" })).toHaveAttribute("href", /releases\/tag\/v9\.1\.0$/);
  await card.getByText("Notes de la version 9.1.0").click();
  await expect(card.getByText("- Tout ce qui manquait.")).toBeVisible();
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
  await viewer.goto("/settings/");
  await expect(viewer.getByRole("heading", { name: "Système" })).toBeVisible();
  await expect(viewer.getByRole("heading", { name: "Mises à jour" })).toHaveCount(0);
});
