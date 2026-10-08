import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// The VPN card of a WireGuard app: a client added, its configuration downloaded, then removed.
test("vpn: add a client, download its configuration, remove it", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "wireguard", name: "Tunnel", inputs: { vpn_port: 51830 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const id = created.app.id as number;
  const clients = async () => (await (await page.request.get(`/api/v1/apps/${id}/vpn`)).json()).clients.map((c: { name: string }) => c.name);

  await page.goto(`/app/?id=${id}`);
  await expect(page.getByText("Aucun client pour l'instant.")).toBeVisible();
  await page.getByLabel("Nom du client (ex. téléphone)").fill("telephone");
  await page.getByRole("button", { name: "Ajouter un client" }).click();
  await expect(page.getByRole("switch", { name: "Activer telephone" })).toBeChecked();
  expect(await clients()).toEqual(["telephone"]);

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Télécharger la configuration de telephone" }).click();
  const conf = readFileSync((await (await download).path())!, "utf8");
  expect(conf).toContain("[Interface]");
  expect(conf).toContain("[Peer]");

  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Supprimer telephone" }).click();
  await expect(page.getByText("Aucun client pour l'instant.")).toBeVisible();
  expect(await clients()).toEqual([]);
});
