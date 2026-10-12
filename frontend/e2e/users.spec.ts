import { expect, test } from "@playwright/test";

import { adminApi, signIn } from "./helpers";

// A user's "⋯" menu opens over the page: the table's scrolling frame neither cuts it nor
// grows a scrollbar, even on the last row; its items act (here: disable, then enable).
test("users: the actions menu opens over the page, not inside the table", async ({ page }) => {
  await signIn(page);
  const { headers } = await adminApi(page);
  const created = await page.request.post("/api/v1/users", {
    headers, data: { username: "menu-test", role: "viewer", password: "temporary-pass-1" },
  }); // prettier-ignore
  expect(created.ok()).toBe(true);
  const disabled = async () =>
    ((await (await page.request.get("/api/v1/users")).json()) as { username: string; disabled: boolean }[]).find((u) => u.username === "menu-test")?.disabled;

  await page.goto("/users/");
  const trigger = page.getByRole("button", { name: "Actions pour menu-test" });
  const frame = page.locator("div.overflow-x-auto").filter({ has: trigger });
  const before = await frame.evaluate((el) => [el.scrollWidth, el.scrollHeight, el.clientWidth, el.clientHeight]);
  await trigger.click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  // The frame did not grow (no scrollbar) and the menu is drawn whole, in the window.
  expect(await frame.evaluate((el) => [el.scrollWidth, el.scrollHeight, el.clientWidth, el.clientHeight])).toEqual(before);
  const box = (await menu.boundingBox())!;
  const view = page.viewportSize()!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(view.height);
  expect(box.x + box.width).toBeLessThanOrEqual(view.width);
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();

  // An item acts (the click is not lost to the outside-click closing).
  await trigger.click();
  await page.getByRole("menuitem", { name: "Désactiver" }).click();
  await expect.poll(disabled).toBe(true);
  await trigger.click();
  await page.getByRole("menuitem", { name: "Réactiver" }).click();
  await expect.poll(disabled).toBe(false);
});
