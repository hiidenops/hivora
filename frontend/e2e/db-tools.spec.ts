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

// A database opened from "Edit": to the local network, then a look at the Internet (the
// usual public warning), and closed again; removed at the end like the one above.
test("db tools: a MariaDB opened to the local network from its settings", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "mariadb", name: "Comptes", inputs: { db_password: "mariadb-pass-123" } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  const id = created.app.id;

  await page.goto(`/edit/?id=${id}`);
  await page.getByText("Réglages avancés", { exact: true }).click();
  const open = page.getByLabel("Ouvrir la base", { exact: true });
  await expect(open).toHaveValue("internal");
  await page.getByLabel("Port sur la machine", { exact: true }).fill("3316");
  await open.selectOption({ label: "À Internet" });
  await page.getByRole("button", { name: "Vérifier les changements" }).click();
  await expect(page.getByText(/Exposé sur Internet/)).toBeVisible();

  await page.getByRole("button", { name: "Retour" }).click();
  await page.getByText("Réglages avancés", { exact: true }).click(); // closed again on the way back
  await open.selectOption({ label: "Au réseau local" });
  await page.getByRole("button", { name: "Vérifier les changements" }).click();
  await expect(page.getByText(/\+ +published: '3316'/)).toBeVisible(); // the compose diff
  await expect(page.getByText(/Exposé sur Internet/)).toBeHidden();
  await page.getByRole("button", { name: "Appliquer", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/apps/${id}/settings`)).json()).values.expose, { timeout: 20_000 }).toBe("lan");

  const removed = await page.request.delete(`/api/v1/apps/${id}`, { headers });
  await done((await removed.json()).id);
});
