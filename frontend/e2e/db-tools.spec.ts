import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// phpMyAdmin's form offers the MariaDB databases deployed in Hivora: none yet, a link to
// deploy one; once there, picking it points phpMyAdmin at it (shown in the compose). The
// database is removed at the end: the later files (the topology's layout) never see it.
test("db tools: phpMyAdmin picks a deployed MariaDB", async ({ page }) => {
  await signIn(page);
  await page.goto("/deploy/?template=phpmyadmin");
  const field = page.getByLabel("Base de données", { exact: true });
  await expect(field).toHaveValue("");
  await expect(page.getByText("Aucune app de ce type n'est déployée.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Déployer mariadb" })).toHaveAttribute("href", /template=mariadb/);

  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "mariadb", name: "Clients", inputs: { db_password: "mariadb-pass-123" } },
  })).json(); // prettier-ignore
  await done(created.job.id);

  await page.reload();
  await page.getByLabel("Nom de l'application", { exact: true }).fill("Admin clients");
  await page.getByLabel("Base de données", { exact: true }).selectOption({ label: "Clients" });
  await expect(page.getByText("Aucune app de ce type n'est déployée.")).toBeHidden();
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Fichier compose généré")).toBeVisible();
  await expect(page.getByText(/PMA_HOST: clients-server-1/)).toBeVisible();

  const removed = await page.request.delete(`/api/v1/apps/${created.app.id}`, { headers });
  await done((await removed.json()).id);
});
