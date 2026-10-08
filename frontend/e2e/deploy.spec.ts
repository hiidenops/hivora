import { expect, test } from "@playwright/test";

import { deployNginx, signIn } from "./helpers";

// The deploy form: a port already taken is reported with a free one to use instead; once
// taken, the preview shows the plan and the compose file, and the app goes online.
test("deploy form: port conflict, suggestion, preview, deployed", async ({ page }) => {
  await signIn(page);
  await deployNginx(page, "Occupant", 8370);

  await page.goto("/deploy/?template=nginx");
  await expect(page.getByRole("heading", { name: /Déployer/, level: 1 })).toBeVisible();
  await page.getByLabel("Nom de l'application", { exact: true }).fill("Boutique");
  await page.getByLabel("Port web", { exact: true }).fill("8370");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Le port 8370/tcp est déjà utilisé par occupant.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Déployer", exact: true })).toBeDisabled();

  await page.getByRole("button", { name: "Utiliser 8371" }).click();
  await expect(page.getByLabel("Port web", { exact: true })).toHaveValue("8371");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Ce que Hivora va faire")).toBeVisible();
  await expect(page.getByText(/:8371 → 80\/tcp \(lan\)/)).toBeVisible();
  await expect(page.getByText("Fichier compose généré")).toBeVisible();

  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByText("Application en ligne")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await expect(page.getByRole("heading", { name: "Boutique" })).toBeVisible();
  const id = new URL(page.url()).searchParams.get("id");
  expect((await (await page.request.get(`/api/v1/apps/${id}/settings`)).json()).values.web_port).toBe(8371);
});
