import { expect, test } from "./test";

import { adminApi, signIn } from "./helpers";

type Zone = { slug: string; name: string; subnet: string };

// The Addressing page: a zone's fixed subnet and its app's fixed IP shown; in advanced mode,
// a subnet over another one refused, another one previewed then applied (the app
// redeployed on it).
test("addressing: the plan shown, a zone's subnet changed by hand", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const zone = (await (await page.request.post("/api/v1/zones", {
    headers, data: { name: "Littoral", color: "#0891b2", network_mode: "shared" },
  })).json()) as Zone; // prettier-ignore
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Phare", zone: zone.slug, inputs: { web_port: 8390 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const base = zone.subnet.split(".").slice(0, 3).join("."); // e.g. 10.100.3

  await page.getByRole("link", { name: "Adressage" }).click();
  await expect(page.getByRole("heading", { name: "Adressage", level: 1 })).toBeVisible();
  const card = page.getByRole("article", { name: "Littoral" });
  await expect(card.getByText(zone.subnet)).toBeVisible();
  await expect(card.getByText("Plage Hivora")).toBeVisible();
  const row = card.getByRole("row", { name: /Phare/ });
  await expect(row.getByText(`${base}.10`)).toBeVisible();
  await expect(card.getByRole("button", { name: "Changer le sous-réseau" })).toHaveCount(0); // simple mode

  await page.getByText("Mode avancé", { exact: true }).click();
  await card.getByRole("button", { name: "Changer le sous-réseau" }).click();
  const dialog = page.getByRole("dialog", { name: "Sous-réseau de la zone « Littoral »" });
  const field = dialog.getByLabel("Sous-réseau", { exact: true });
  await field.fill("10.254.254.0/25"); // over the Administration zone's network
  await dialog.getByRole("button", { name: "Aperçu" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Ce réseau chevauche 10.254.254.0/24, déjà utilisé.");
  await field.fill("172.20.9.0/24");
  await dialog.getByRole("button", { name: "Aperçu" }).click();
  await expect(dialog.getByText("Redéployées : Phare.")).toBeVisible();
  await expect(dialog.getByText(`docker network create --subnet 172.20.9.0/24 hivora-zone-${zone.slug}`)).toBeVisible();
  await dialog.getByRole("button", { name: "Appliquer" }).click();
  await expect(dialog).toBeHidden();
  await expect(card.getByText("172.20.9.0/24")).toBeVisible();
  await expect(card.getByText("Choisi à la main")).toBeVisible();
  await expect(card.getByRole("row", { name: /Phare/ }).getByText("172.20.9.10")).toBeVisible();
});
