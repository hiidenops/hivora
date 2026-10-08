import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// The game panel of a Minecraft server: the whitelist turned on (a new revision applied by a
// job; the setting follows). Players are left out: the fake Docker answers no `list` output.
test("games: whitelist turned on", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "minecraft", name: "Survie", inputs: { eula: true, game_port: 25570 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const id = created.app.id as number;

  await page.goto(`/app/?id=${id}`);
  await page.getByRole("button", { name: "Accès", exact: true }).click();
  const whitelist = page.getByRole("switch", { name: /Liste blanche/ });
  await expect(whitelist).not.toBeChecked();
  await expect(page.getByText("Désactivée : tout le monde peut se connecter.")).toBeVisible();
  page.once("dialog", (d) => void d.accept());
  const put = page.waitForResponse((r) => r.url().endsWith("/game/lists/whitelist/enabled") && r.request().method() === "PUT");
  await whitelist.check();
  await done((await (await put).json()).id); // the new revision, applied
  await expect(page.getByText("Activée : seuls les joueurs de la liste peuvent se connecter.")).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/apps/${id}/settings`)).json()).values.enable_whitelist, {
    timeout: 20_000,
  }).toBe(true);
});
