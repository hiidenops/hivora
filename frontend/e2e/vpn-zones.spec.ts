import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// A VPN serves zones, not apps: from its card, a zone is linked (what closes is listed first);
// the deploy form then offers three accesses, and "through a VPN" lists the zones it serves.
test("vpn zones: link a zone from the VPN card, deploy into it through the VPN", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  await page.request.post("/api/v1/zones", { headers, data: { name: "Coffre-fort", color: "#4f46e5" } });
  const vpn = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "wireguard", name: "Tunnel", inputs: { host: "vpn.example.org", vpn_port: 51870 } },
  })).json(); // prettier-ignore
  await done(vpn.job.id);

  await page.goto(`/app/?id=${vpn.app.id}`);
  const zone = page.getByRole("group", { name: "Zones accessibles par le VPN" }).locator("label", { hasText: "Coffre-fort" });
  await expect(zone).toContainText("0 app(s)");
  await zone.getByRole("switch").check();
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Zones desservies par ce VPN : Coffre-fort");
    expect(d.message()).toContain("Aucun port publié à fermer.");
    void d.accept();
  });
  await page.getByRole("group", { name: "Zones accessibles par le VPN" }).getByRole("button", { name: "Enregistrer" }).click();
  await expect(zone).toContainText("desservie : réseau 10.8.1.0/24", { timeout: 20_000 });

  await page.goto("/deploy/?template=vaultwarden");
  const access = page.getByRole("radiogroup");
  await expect(access.getByRole("radio", { name: /Réseau local/ })).toHaveAttribute("aria-checked", "true");
  await access.getByRole("radio", { name: /Par un VPN/ }).click();
  await expect(page.getByLabel("Zone", { exact: true })).toHaveValue("coffre-fort");
  await expect(page.getByLabel("Zone", { exact: true }).locator("option")).toHaveText(["Coffre-fort (VPN Tunnel)"]);
  await expect(access.getByRole("radio", { name: /Par un VPN/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Ce que Hivora va faire")).toBeVisible();
  await expect(page.getByText(/→ 80\/tcp/)).toHaveCount(0); // nothing published
});
