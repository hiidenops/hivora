import { expect, test } from "@playwright/test";

import { PASSWORD } from "./helpers";
import { HOST, VPN_PORT } from "./host";

// A panel with the admin VPN (its own server, HIVORA_ACCESS=vpn): set up on start, its
// client shown as the admin access, which cannot be disabled nor deleted.
test.use({ baseURL: `http://${HOST}:${VPN_PORT}` });

test("admin VPN: set up on start, its client protected", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill("admin");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.getByLabel("Mot de passe actuel", { exact: true }).fill("admin");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();

  const apps = async () => (await (await page.request.get("/api/v1/apps")).json()) as { id: number; slug: string }[];
  await expect.poll(async () => (await apps()).map((a) => a.slug), { timeout: 30_000 }).toEqual(["admin-vpn"]);
  const id = (await apps())[0].id;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/apps/${id}/vpn`)).json()).clients.length, { timeout: 30_000 }).toBe(1);

  await page.goto(`/app/?id=${id}`);
  await expect(page.getByText("Accès d'administration")).toBeVisible();
  await expect(page.getByRole("switch", { name: "Activer admin" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Supprimer admin" })).toHaveCount(0);

  const { clients } = await (await page.request.get(`/api/v1/apps/${id}/vpn`)).json();
  const csrf = (await (await page.request.get("/api/v1/auth/me")).json()).csrf_token as string;
  const refused = await page.request.delete(`/api/v1/apps/${id}/vpn/clients/${clients[0].id}`, { headers: { "X-CSRF-Token": csrf } });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error.code).toBe("admin_vpn_protected");
});
