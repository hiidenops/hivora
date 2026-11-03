import { expect, test } from "./test";

import { adminApi, signIn } from "./helpers";

// A TeamSpeak 3 server's panel, its ServerQuery answered by e2e_app (FakeTeamSpeak): a client
// banned, the server password set, a new admin key shown once.
test("teamspeak: ban, password, admin key", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  // Its ports are fixed (30033): an earlier attempt's server goes first.
  for (const app of await (await page.request.get("/api/v1/apps")).json()) {
    if (app.template === "teamspeak") await done((await (await page.request.delete(`/api/v1/apps/${app.id}?remove_data=true`, { headers })).json()).id);
  }
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "teamspeak", name: "Voix", inputs: { eula: true } },
  })).json(); // prettier-ignore
  await done(created.job.id);

  await page.goto("/");
  await expect(page.getByText("1 / 32 connectés")).toBeVisible(); // on the dashboard's tile
  await page.goto(`/app/?id=${created.app.id}`);
  await expect(page.getByText("TeamSpeak ]I[ Server")).toBeVisible();
  const clients = page.getByRole("button", { name: "Connectés" });
  const row = page.getByRole("row", { name: /Alice Liddell/ });
  if (!(await row.isVisible())) await clients.click();
  await expect(row).toContainText("198.51.100.4");

  await row.getByRole("button", { name: "Bannir Alice Liddell" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Raison").fill("spam");
  await dialog.getByRole("button", { name: "Bannir" }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: "Bans" }).click();
  await expect(page.getByRole("row", { name: /198\.51\.100\.4 spam/ }).first()).toBeVisible();

  await page.getByRole("button", { name: "Mot de passe du serveur" }).click();
  await page.getByRole("dialog").getByLabel("Nouveau mot de passe").fill("les-copains");
  await page.getByRole("dialog").getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByText("Défini", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Clé admin" }).click();
  await expect(page.getByText("1 clé(s) pas encore utilisée(s)", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Générer une nouvelle clé" }).click();
  await expect(page.getByText("Copiez-la maintenant")).toBeVisible();
  await expect(page.getByRole("button", { name: /^newkey/ })).toBeVisible();
});
