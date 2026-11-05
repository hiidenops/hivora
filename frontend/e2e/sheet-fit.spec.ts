import { expect, test } from "./test";

import { deployNginx, openAppMenu, signIn } from "./helpers";

// A side panel opens as wide as its content needs: the compose editor's longest line (the
// image pinned by its digest) shows whole, without scrolling sideways.
test("side panel: opens as wide as the compose editor's longest line", async ({ page }) => {
  await signIn(page);
  const id = (await deployNginx(page, "Largeur", 8393)).app.id;
  await page.goto(`/app/?id=${id}`);
  await page.getByText("Mode avancé", { exact: true }).click();
  await openAppMenu(page, "Détails avancés");
  await page.getByRole("button", { name: "Modifier le compose" }).click();
  await expect(page.getByRole("textbox", { name: "Modifier le compose" })).toHaveText(/sha256:/);
  const scroller = page.locator(".cm-scroller").first();
  await expect.poll(() => scroller.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  const panel = page.getByRole("dialog");
  expect((await panel.boundingBox())!.width).toBeGreaterThan(768); // wider than the default
});
