import { DatabaseSync } from "node:sqlite";

import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// An app deployed from an older catalog version is marked on the dashboard: a pill on its
// card (the versions in its tooltip, a link to its page) and the count in the header.
test("dashboard marks an app with a newer catalog version", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "adminer", name: "Vieil Adminer", inputs: { web_port: 8363 } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const db = new DatabaseSync("/tmp/hivora-e2e/data/hivora.db");
  db.exec("UPDATE template_version SET version = '0.0.1' WHERE slug = 'adminer'");
  db.close();

  await page.goto("/");
  const pill = page.getByRole("link", { name: "Mise à jour" });
  await expect(pill).toHaveCount(1);
  await expect(pill).toHaveAttribute("title", /^Version .+ disponible \(actuelle 0\.0\.1\)$/);
  await expect(page.getByText("1 mise(s) à jour disponible(s)")).toBeVisible();
  await pill.click();
  await expect(page.getByRole("heading", { name: "Vieil Adminer", level: 1 })).toBeVisible();
});
