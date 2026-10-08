import { expect, test } from "@playwright/test";

import { adminApi, deployNginx, openAppMenu, signIn } from "./helpers";

// The code editor (CodeMirror) where text is written by hand, besides the site files
// (sites-page.spec.ts): the hand-written compose and a long text field of a form.

test("code editor: the compose, YAML colored, Tab indents, Ctrl+S checks, then applied", async ({ page }) => {
  await signIn(page);
  const { done } = await adminApi(page);
  const id = (await deployNginx(page, "Gabarit", 8392)).app.id;

  await page.goto(`/app/?id=${id}`);
  await page.getByText("Mode avancé", { exact: true }).click();
  await openAppMenu(page, "Détails avancés");
  await page.getByRole("button", { name: "Modifier le compose" }).click();
  const editor = page.getByRole("textbox", { name: "Modifier le compose" });
  await expect(editor).toHaveText(/services:/);
  await expect(editor.locator("span").first()).toBeVisible(); // YAML tokens colored

  await editor.press("Control+End");
  await editor.press("Enter");
  await editor.press("Tab"); // indents, the focus stays in the editor
  await expect(editor).toBeFocused();
  await editor.pressSequentially("# note");
  await editor.press("Control+s"); // checks (applying stays a click)
  await expect(page.getByText("Compose valide.")).toBeVisible({ timeout: 20_000 });

  const applied = page.waitForResponse((r) => r.url().endsWith(`/apps/${id}/compose`) && r.request().method() === "PUT");
  await page.getByRole("button", { name: "Appliquer ce compose" }).click();
  await done((await (await applied).json()).id);
  const compose = (await (await page.request.get(`/api/v1/apps/${id}/compose`)).json()).compose_yaml as string;
  expect(compose).toContain("  # note");
});

test("code editor: a long text field of the deploy form, typed and completed from the suggestions", async ({ page }) => {
  await signIn(page);
  await page.goto("/deploy/?template=minecraft");
  await page.getByLabel("Nom de l'application", { exact: true }).fill("Créatif");
  await page.getByLabel(/J'accepte le contrat de licence Minecraft/).check();
  await page.getByText("Réglages avancés", { exact: true }).click();
  await page.getByLabel("Port de jeu (TCP)", { exact: true }).fill("25580");

  const field = page.getByRole("textbox", { name: "Propriétés personnalisées (server.properties)" });
  await field.fill("motd=Bonjour\n");
  await page.getByText("Propriétés disponibles", { exact: true }).click();
  await page.getByRole("button", { name: /^force-gamemode=false/ }).click();
  await expect(field).toHaveText(/motd=Bonjour.*force-gamemode=false/);

  await page.getByRole("button", { name: "Vérifier" }).click();
  await page.getByRole("button", { name: "Déployer", exact: true }).click();
  await expect(page.getByText("Application en ligne")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Voir l'application" }).click();
  await expect(page.getByRole("heading", { name: "Créatif" })).toBeVisible();
  const id = new URL(page.url()).searchParams.get("id");
  const values = (await (await page.request.get(`/api/v1/apps/${id}/settings`)).json()).values;
  expect(values.custom_properties).toContain("motd=Bonjour");
  expect(values.custom_properties).toContain("force-gamemode=false");
});
