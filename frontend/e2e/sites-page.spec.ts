import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { adminApi, deployNginx, expectPointerCursors, signIn, signInViewer } from "./helpers";

// The page of one site an nginx hosts (/app/site/?app=&site=): the content and file cards
// on /apps/{app}/sites/{site}, never on the older /sites routes; the site's own folder only.
test("hosted site page: zip, read, create, edit, conflict, viewer, back to the nginx", async ({ page, browser }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);

  // A host with one added site (set up through the API).
  const created = await deployNginx(page, "Atelier", 8320);
  const app = created.app.id;
  expect((await page.request.post(`/api/v1/apps/${app}/sites/hosting`, { headers })).status()).toBe(200);
  const added = await (await page.request.post(`/api/v1/apps/${app}/sites`, { headers, data: { name: "Docs", port: 8321 } })).json();
  await done(added.config_job.id);
  const site = added.site.id;
  const base = `/api/v1/apps/${app}/sites/${site}`;
  const disk = "/tmp/hivora-e2e/srv/atelier";

  // Every request the page makes for content and files.
  const calls: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url()).pathname;
    if (/\/(content|files)/.test(url)) calls.push(`${r.method()} ${url}`);
  });

  await page.goto(`/app/site/?app=${app}&site=${site}`);
  const crumbs = page.getByRole("navigation", { name: "Fil d'Ariane" });
  await expect(crumbs).toHaveText(/Atelier.*Docs/);
  await expect(page.getByRole("heading", { name: "Docs", level: 1 })).toBeVisible();
  await expect(page.getByText("Port 8321")).toBeVisible();
  await expect(page.getByText("Actif", { exact: true })).toBeVisible();
  const open = page.getByRole("link", { name: "Ouvrir le site" });
  await expect(open).toHaveAttribute("href", /^http:\/\/[\d.]+:8321$/);
  await expect(open).toHaveAttribute("target", "_blank");
  await expect(page.getByText("Aucun fichier", { exact: false })).toBeVisible(); // a new site: empty folder
  await expect(crumbs.getByRole("link", { name: "Sites", exact: true })).toHaveAttribute("href", "/sites/");

  // An empty site: a first page in one click, titled with its name.
  await page.getByRole("button", { name: "Créer index.html" }).click();
  await expect(page.getByRole("list", { name: "Fichiers" }).getByRole("button")).toHaveText([/index\.html/], { timeout: 20_000 });
  await expect.poll(() => existsSync(`${disk}/sites/docs/index.html`)).toBe(true);
  expect(readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toContain("<h1>Docs</h1>");
  await expect(page.getByText("Ce site est vide", { exact: false })).toBeHidden();

  // A zip: in the site's own folder, the main site untouched.
  const mainTree = () => (existsSync(`${disk}/html`) ? readdirSync(`${disk}/html`, { recursive: true }).sort() : []);
  const mainBefore = mainTree();
  await page.getByLabel("Archive .zip du site").setInputFiles(path.join(__dirname, "fixtures", "site.zip"));
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Remplacer le contenu" }).click();
  await expect(page.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  const list = page.getByRole("list", { name: "Fichiers" });
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/], { timeout: 20_000 });
  expect(readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toContain("Depuis le ZIP");
  expect(mainTree()).toEqual(mainBefore);

  // Read, then edit and save.
  await list.getByRole("button", { name: /index\.html/ }).click();
  const editor = page.getByLabel("Contenu de index.html");
  await expect(editor).toHaveValue(/Depuis le ZIP/);
  const save = page.getByRole("button", { name: "Enregistrer" });
  await expect(save).toBeDisabled();
  await editor.fill("<h1>Docs</h1>\n");
  await save.click();
  await expect(page.getByText("Enregistrement d'un fichier")).toBeVisible();
  await expect(page.getByText("Modifications non enregistrées")).toBeHidden({ timeout: 20_000 });
  await expect.poll(() => readFileSync(`${disk}/sites/docs/index.html`, "utf8")).toBe("<h1>Docs</h1>\n");

  // Saved meanwhile by someone else: file_changed, then reloaded on request.
  await editor.fill("<h1>Ma version</h1>\n");
  const read = await (await page.request.get(`${base}/files/content?path=index.html`)).json();
  const other = await (await page.request.put(`${base}/files/content`, {
    headers, data: { path: "index.html", content: "<h1>Leur version</h1>\n", base_sha256: read.sha256 },
  })).json(); // prettier-ignore
  await done(other.id);
  await save.click();
  await expect(page.getByText("Le fichier a changé depuis son ouverture.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Recharger" }).click();
  await expect(editor).toHaveValue("<h1>Leur version</h1>\n");

  // A new file in a new folder.
  await page.getByLabel("Nouveau fichier").fill("js/app.js");
  await page.getByRole("button", { name: "Créer" }).click();
  await page.getByLabel("Contenu de js/app.js").fill("console.log('docs');\n");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(list.getByRole("button")).toHaveText([/css\/site\.css/, /index\.html/, /js\/app\.js/], { timeout: 20_000 });
  expect(existsSync(`${disk}/sites/docs/js/app.js`)).toBe(true);
  expect(mainTree()).toEqual(mainBefore);
  await expectPointerCursors(page);

  // The page used the hosted site's routes only.
  expect(calls.length).toBeGreaterThan(0);
  expect(calls.filter((c) => !c.split(" ")[1].startsWith(`${base}/`))).toEqual([]);

  // Back to the nginx.
  await crumbs.getByRole("link", { name: "Atelier" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/\\?id=${app}$`));
  await expect(page.getByRole("list", { name: "Sites" }).getByRole("listitem", { name: "Docs" })).toBeVisible();

  // A viewer reads, writes nothing.
  const viewer = await signInViewer(page, browser, "vera");
  await viewer.goto(`/app/site/?app=${app}&site=${site}`);
  await viewer.getByRole("list", { name: "Fichiers" }).getByRole("button", { name: /js\/app\.js/ }).click();
  const readOnly = viewer.getByLabel("Contenu de js/app.js");
  await expect(readOnly).toHaveValue("console.log('docs');\n");
  await expect(readOnly).toHaveAttribute("readonly", "");
  await expect(viewer.getByRole("button", { name: "Enregistrer" })).toHaveCount(0);
  await expect(viewer.getByLabel("Nouveau fichier")).toHaveCount(0);
  await expect(viewer.getByRole("button", { name: "Remplacer le contenu" })).toHaveCount(0);
  await viewer.close();
});
