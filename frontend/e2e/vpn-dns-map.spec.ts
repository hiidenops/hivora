import { expect, test } from "./test";

import { adminApi, signIn } from "./helpers";

// The VPN's DNS as a map: a name added becomes a card; linked to a site of an nginx (its
// own port) it opens without the port (through the web proxy); unlinked, then removed.
test("vpn dns map: a name linked to a site, then unlinked and removed", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  await page.request.post("/api/v1/zones", { headers, data: { name: "Carte DNS", color: "#0891b2", network_mode: "shared" } });
  const vpn = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "wireguard", name: "Passage", inputs: { host: "vpn.example.org", vpn_port: 51874, vpn_subnet: "10.7.0.0/24" }, vpn_zones: ["carte-dns"] },
  })).json(); // prettier-ignore
  await done(vpn.job.id);
  const nginx = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Atelier", zone: "carte-dns", inputs: { web_port: 8395 } },
  })).json(); // prettier-ignore
  await done(nginx.job.id);
  expect((await page.request.post(`/api/v1/apps/${nginx.app.id}/sites/hosting`, { headers })).ok()).toBe(true);
  expect((await page.request.post(`/api/v1/apps/${nginx.app.id}/sites`, { headers, data: { name: "Carnet", port: 8396 } })).ok()).toBe(true);

  await page.goto(`/app/?id=${vpn.app.id}`);
  await page.getByRole("button", { name: "DNS", exact: true }).click();
  const map = page.getByRole("dialog", { name: "DNS du VPN Passage" });
  await expect(map.getByText("Site « Carnet »")).toBeVisible();
  await map.getByLabel("Nom de domaine").fill("carnet.lan");
  await map.getByRole("button", { name: "Ajouter un nom" }).click();
  const target = map.getByLabel("Cible de carnet.lan");
  await expect(target).toHaveValue(""); // a card, not linked yet

  await target.selectOption({ label: "Atelier · Carnet :8396" });
  await expect(map.getByRole("link", { name: /http:\/\/carnet\.lan/ })).toContainText("sans le port 8396");
  await target.selectOption({ label: "Non relié" });
  await expect(map.getByRole("link", { name: /http:\/\/carnet\.lan/ })).toHaveCount(0);
  await map.getByRole("button", { name: "Supprimer carnet.lan" }).click();
  await expect(map.getByLabel("Cible de carnet.lan")).toHaveCount(0);

  // Left as found: the next files see their own zones and VPNs only.
  for (const id of [nginx.app.id, vpn.app.id]) {
    await done((await (await page.request.delete(`/api/v1/apps/${id}`, { headers })).json()).id);
  }
  expect((await page.request.delete("/api/v1/zones/carte-dns", { headers })).ok()).toBe(true);
});
