import { expect, test } from "./test";

import { adminApi, signIn } from "./helpers";

// System → the host's packages, through the (fake) host agent: off first, then checked,
// upgraded by a job, and the reboot's list shown (not run: the fake host never reboots).
test("host updates: checked, upgraded, the reboot listed", async ({ page }) => {
  await signIn(page);
  await page.goto("/system/");
  const card = page.locator("main");
  await expect(card.getByRole("link", { name: "Activer l'agent hôte (Pare-feu)" })).toBeVisible();

  const { headers } = await adminApi(page);
  const agent = (enabled: boolean) => page.request.put("/api/v1/host-firewall/agent", { headers, data: { enabled } });
  expect((await agent(true)).ok()).toBe(true);
  try {
    await page.reload();
    await card.getByRole("button", { name: "Vérifier", exact: true }).click();
    await expect(card.getByText("2 paquet(s) à mettre à jour")).toBeVisible();
    await expect(card.getByText("dont 1 de sécurité")).toBeVisible();
    await card.getByText("Voir les 2 paquet(s)").click();
    await expect(card.getByText("3.0.15-1 → 3.0.17-1")).toBeVisible();

    page.once("dialog", (d) => d.accept());
    await card.getByRole("button", { name: "Mettre à jour les paquets" }).click();
    await expect(card.getByText("Paquets mis à jour.")).toBeVisible({ timeout: 15_000 });

    await card.getByRole("button", { name: "Redémarrer", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Redémarrer la machine" });
    await expect(dialog.getByText(/Apps arrêtées puis relancées par Hivora/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Arrêter les apps et redémarrer" })).toBeEnabled();
    await page.keyboard.press("Escape");
  } finally {
    await agent(false);
  }
});
