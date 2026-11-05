import { expect, test } from "./test";

import { adminApi, signIn } from "./helpers";

// A zone removed with everything in it: what goes is listed, the data kept by default, the
// zone's name typed to confirm; the zone and its app are gone.
test("zones: remove a zone and everything in it", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  await page.request.post("/api/v1/zones", { headers, data: { name: "Démolition", color: "#e11d48", network_mode: "shared" } });
  const app = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name: "Cabane", zone: "demolition", inputs: { web_port: 8397 } },
  })).json(); // prettier-ignore
  await done(app.job.id);

  await page.goto("/zones/");
  const card = page.getByRole("article", { name: "Démolition" });
  await card.getByRole("button", { name: "Supprimer la zone et tout son contenu" }).click();
  const dialog = page.getByRole("dialog", { name: "Supprimer « Démolition » et tout son contenu" });
  await expect(dialog.getByText("Cabane", { exact: true })).toBeVisible();
  await expect(dialog.getByText("cabane-server-1")).toBeVisible();
  await expect(dialog.getByRole("switch")).not.toBeChecked(); // data kept unless asked
  const run = dialog.getByRole("button", { name: "Tout supprimer" });
  await expect(run).toBeDisabled();
  await dialog.getByLabel(/Pour confirmer/).fill("Démolition");
  await run.click();
  await expect(dialog).toBeHidden();
  await expect(card).toBeHidden({ timeout: 30_000 });
  expect((await page.request.get(`/api/v1/apps/${app.app.id}`)).status()).toBe(404);
});
