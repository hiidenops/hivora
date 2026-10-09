import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { adminApi, deployNginx, signIn } from "./helpers";

type Graph = { nodes: { type: string; label?: string; kind?: string; host?: string }[] };

/** The topology as the API returns it. */
async function graph(page: Page): Promise<Graph> {
  return (await page.request.get("/api/v1/topology")).json();
}

// The topology page, pinned before its view is split: the graph, the inspector, a declared
// element added, changed and removed, a prepared change (kept across a reload, then
// discarded), and the JSON export.
test("topology: graph, inspector, declared element, prepared change, JSON export", async ({ page }) => {
  await signIn(page);
  const carto = (await deployNginx(page, "Carto", 8340)).app.id;

  // The graph: the app, Internet, the detail levels, the legend.
  await page.getByRole("link", { name: "Topologie", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Topologie", level: 1 })).toBeVisible();
  const flow = page.locator(".react-flow");
  const node = (text: string) => flow.locator(".react-flow__node").filter({ hasText: text });
  await expect(node("Carto")).toBeVisible();
  await expect(node("Internet")).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Niveau de détail" }).getByRole("tab")).toHaveText(["Zones", "Zones et apps", "Tout (ports)"]);
  await expect(page.getByRole("tab", { name: "Zones et apps" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("port public (contourne le pare-feu)")).toBeVisible();

  // The inspector of an app: its name, its port's exposure, a link to its page; closed.
  await node("Carto").click();
  const inspector = page.locator("aside").filter({ has: page.getByRole("heading", { name: "Carto" }) });
  await expect(inspector).toBeVisible();
  await expect(inspector.getByLabel("Exposition de 80/tcp")).toHaveValue("lan");
  await expect(inspector.getByRole("link", { name: "Ouvrir l'app" })).toHaveAttribute("href", `/app/?id=${carto}`);
  await inspector.getByRole("button", { name: "Fermer" }).click();
  await expect(inspector).toBeHidden();

  // A declared element: added, changed, removed (the API agrees each time).
  await page.getByRole("button", { name: "Ajouter un élément" }).click();
  await page.getByLabel("Type", { exact: true }).selectOption("router");
  await page.getByLabel("Libellé", { exact: true }).fill("Box du salon");
  await page.getByRole("button", { name: "Ajouter", exact: true }).click();
  await expect(node("Box du salon")).toBeVisible();
  const declared = async () => (await graph(page)).nodes.filter((n) => n.type === "declared").map((n) => [n.kind, n.label]);
  expect(await declared()).toEqual([["router", "Box du salon"]]);

  await node("Box du salon").click();
  const box = page.locator("aside").filter({ has: page.getByRole("heading", { name: "Box du salon" }) });
  await box.getByLabel("Type", { exact: true }).selectOption("note");
  await box.getByLabel("Libellé", { exact: true }).fill("Box Freebox");
  await box.getByRole("button", { name: "Enregistrer" }).click();
  await expect(node("Box Freebox")).toBeVisible();
  await expect.poll(declared).toEqual([["note", "Box Freebox"]]);

  await node("Box Freebox").click();
  page.once("dialog", (dialog) => void dialog.accept());
  await page.locator("aside").getByRole("button", { name: "Supprimer l'élément" }).click();
  await expect(node("Box Freebox")).toHaveCount(0);
  await expect.poll(declared).toEqual([]);

  // A prepared change: nothing applied, listed, kept across a reload, then discarded.
  await node("Carto").click();
  await inspector.getByLabel("Exposition de 80/tcp").selectOption("public");
  const pending = page.getByRole("button", { name: "1 modification(s) en attente" });
  await expect(pending).toBeVisible();
  await pending.click();
  const panel = page.getByRole("region", { name: "1 modification(s) en attente" });
  await expect(panel.getByRole("listitem")).toHaveText(["Carto : port 80/tcp → public"]);
  await expect(panel.getByText("Rien n'est encore appliqué", { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "1 modification(s) en attente" })).toBeVisible();
  await page.getByRole("button", { name: "Annuler les modifications" }).click();
  await expect(page.getByRole("button", { name: /modification\(s\) en attente/ })).toHaveCount(0);
  const ports = (await (await page.request.get(`/api/v1/apps/${carto}/settings`)).json()).overrides;
  expect(JSON.stringify(ports)).not.toContain("public"); // nothing was applied

  // The JSON export: the graph as the API gives it.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Exporter en JSON" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("hivora-topology.json");
  const exported = JSON.parse(readFileSync((await file.path())!, "utf8")) as Graph;
  expect(exported.nodes.map((n) => n.label)).toContain("Carto");
  expect(exported.nodes.some((n) => n.type === "internet")).toBe(true);

  // Each site an nginx hosts is a node under it, its inspector leading to the site's page.
  const { headers, done } = await adminApi(page);
  await page.request.post(`/api/v1/apps/${carto}/sites/hosting`, { headers });
  const atlas = await (await page.request.post(`/api/v1/apps/${carto}/sites`, { headers, data: { name: "Atlas", port: 8342 } })).json();
  await done(atlas.config_job.id);
  await page.reload();
  await expect(node("Atlas")).toContainText(":8342");
  await expect(node("Carto").filter({ hasText: ":8340" })).toHaveCount(1); // its main site, port on its card
  await node("Atlas").click();
  const site = page.locator("aside").filter({ has: page.getByRole("heading", { name: "Atlas" }) });
  await expect(site.getByText("Site hébergé par Carto", { exact: false })).toBeVisible();
  await expect(site.getByRole("link", { name: "Configurer" })).toHaveAttribute("href", `/app/site/?app=${carto}&site=${atlas.site.id}`);
  const graphSites = (await graph(page)).nodes.filter((n) => n.type === "site" && n.host === `app:${carto}`).map((n) => n.label);
  expect(graphSites).toEqual(["Carto", "Atlas"]);
});
