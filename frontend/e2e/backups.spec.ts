import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { deployNginx, signIn } from "./helpers";

// The app's backups card: a manual backup taken, then restored (the volume's file is back
// as it was when archived).
test("backups: back up now, then restore the data", async ({ page }) => {
  await signIn(page);
  const id = (await deployNginx(page, "Coffre", 8360)).app.id;
  const html = "/tmp/hivora-e2e/srv/coffre/html";
  mkdirSync(html, { recursive: true });
  writeFileSync(`${html}/index.html`, "version 1");

  await page.goto(`/app/?id=${id}`);
  await page.getByRole("button", { name: "Sauvegardes" }).click();
  await page.getByRole("button", { name: "Sauvegarder maintenant" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "manuelle" });
  await expect(row).toHaveCount(1);
  await expect(row.getByLabel("Télécharger l'archive")).toBeVisible({ timeout: 20_000 }); // archived
  const backups = async () => (await (await page.request.get(`/api/v1/apps/${id}/backups`)).json()).backups;
  expect((await backups()).map((b: { status: string; scheduled: boolean }) => [b.status, b.scheduled])).toEqual([["ok", false]]);

  writeFileSync(`${html}/index.html`, "version 2");
  page.once("dialog", (d) => void d.accept());
  await row.getByRole("button", { name: "Restaurer cette sauvegarde" }).click();
  await expect.poll(() => readFileSync(`${html}/index.html`, "utf8"), { timeout: 20_000 }).toBe("version 1");
});
