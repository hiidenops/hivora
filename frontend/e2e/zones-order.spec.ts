import { expect, test } from "@playwright/test";

import { adminApi, signIn, signInViewer } from "./helpers";

// A zone's start order: dependencies set through the keyboard list (the graph follows: two
// columns, two arrows), a loop refused at once, saved; then the zone started in that order
// (one job, followed in a pop-up). A viewer sees the order, changes nothing.
test("zones: start order with arrows, then the zone started in that order", async ({ page, browser }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);
  expect((await page.request.post("/api/v1/zones", { headers, data: { name: "Ordre", color: "#3b82f6" } })).ok()).toBe(true);
  const ids: Record<string, number> = {};
  for (const [name, port] of [["Base", 8501], ["Cache", 8502], ["Web", 8503]] as const) {
    const r = await (await page.request.post("/api/v1/apps", {
      headers, data: { template: "nginx", name, zone: "ordre", inputs: { web_port: port } },
    })).json(); // prettier-ignore
    await done(r.job.id);
    ids[name] = r.app.id;
  }

  await page.goto("/zones/");
  const card = page.getByRole("article", { name: "Ordre" });
  await card.getByRole("button", { name: "Ordre de démarrage" }).click();
  const sheet = page.getByRole("dialog", { name: "Ordre de démarrage : Ordre" });
  const graph = sheet.getByRole("figure", { name: "Graphe de l'ordre de démarrage" });
  await expect(graph.getByText("Étape 1")).toBeVisible();
  await expect(graph.getByText("Étape 2")).toBeHidden(); // no dependency yet: one column

  // Web starts after Base (an arrow drawn in the graph, from Base's right edge to Web's left
  // edge) and after Cache (through the list): two columns, two arrows.
  const webAfter = sheet.getByRole("group", { name: "Web démarre après" });
  const handle = (app: string, side: "source" | "target") =>
    graph.locator(".react-flow__node").filter({ hasText: app }).locator(`.react-flow__handle.${side}`);
  const from = (await handle("Base", "source").boundingBox())!;
  const to = (await handle("Web", "target").boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(webAfter.getByRole("checkbox", { name: "Base" })).toBeChecked();
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await webAfter.getByRole("checkbox", { name: "Cache" }).check();
  await expect(graph.getByText("Étape 2")).toBeVisible();
  await expect(graph.locator(".react-flow__edge")).toHaveCount(2);
  await expect(sheet.getByText("Modifications non enregistrées")).toBeVisible();
  // A loop is refused at once, with the apps named; nothing changes.
  await sheet.getByRole("group", { name: "Base démarre après" }).getByRole("checkbox", { name: "Web" }).click();
  await expect(sheet.getByText("Boucle refusée", { exact: false })).toContainText("Base → Web");
  await expect(sheet.getByRole("group", { name: "Base démarre après" }).getByRole("checkbox", { name: "Web" })).not.toBeChecked();
  await expect(graph.locator(".react-flow__edge")).toHaveCount(2);
  // An arrow clicked in the graph is removed (the list follows), then put back by the list.
  await graph.getByRole("group", { name: "Cache → Web" }).or(graph.locator(".react-flow__edge").last()).first().click();
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await expect(webAfter.getByRole("checkbox", { name: "Cache" })).not.toBeChecked();
  await webAfter.getByRole("checkbox", { name: "Cache" }).check();
  await expect(graph.locator(".react-flow__edge")).toHaveCount(2);
  await sheet.getByRole("button", { name: "Enregistrer" }).click();
  await expect(sheet.getByText("Modifications non enregistrées")).toBeHidden();
  const saved = await (await page.request.get("/api/v1/zones/ordre/startup")).json();
  expect(saved.dependencies).toEqual([{ app: ids.Web, after: ids.Base }, { app: ids.Web, after: ids.Cache }]);
  expect(saved.steps).toEqual([[ids.Base, ids.Cache], [ids.Web]]);
  await page.keyboard.press("Escape");

  // Started in that order: the confirmation shows it, one job in a pop-up.
  page.once("dialog", (d) => {
    expect(d.message()).toContain("1. Base, Cache");
    expect(d.message()).toContain("2. Web");
    void d.accept();
  });
  await card.getByRole("button", { name: "Démarrer", exact: true }).click();
  const toast = page.getByRole("region", { name: "Suivi des tâches" }).getByRole("status", { name: "Démarrage ou arrêt d'une zone" });
  await expect(toast.getByText("Réussi")).toBeVisible({ timeout: 30_000 });

  // A viewer: the order, read only; no action.
  const viewer = await signInViewer(page, browser, "zone-viewer");
  await viewer.goto("/zones/");
  const seen = viewer.getByRole("article", { name: "Ordre" });
  await expect(seen.getByRole("button", { name: "Démarrer", exact: true })).toHaveCount(0);
  await seen.getByRole("button", { name: "Ordre de démarrage" }).click();
  const box = viewer.getByRole("dialog").getByRole("group", { name: "Web démarre après" }).getByRole("checkbox", { name: "Base" });
  await expect(box).toBeChecked();
  await expect(box).toBeDisabled();
  await viewer.close();
});
