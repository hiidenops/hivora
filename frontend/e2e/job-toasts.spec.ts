import { expect, test } from "@playwright/test";

import { deployNginx, signIn } from "./helpers";

// A job started from a page is followed in a pop-up over the page (nothing moves): closed
// 5 s after it succeeded, or at once by its button.
test("job pop-ups: over the page, closed by themselves after success or by their button", async ({ page }) => {
  await signIn(page);
  const id = (await deployNginx(page, "Signal", 8395)).app.id;
  await page.goto(`/app/?id=${id}`);
  const toasts = page.getByRole("region", { name: "Suivi des tâches" });
  const heading = page.getByRole("heading", { name: "Signal", level: 1 });
  const before = await heading.boundingBox();

  await page.getByRole("button", { name: "Arrêter", exact: true }).click();
  const stop = toasts.getByRole("status", { name: "Arrêt" });
  await expect(stop).toBeVisible();
  expect(await heading.boundingBox()).toEqual(before); // the page did not move
  await expect(stop.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await expect(stop).toBeHidden({ timeout: 10_000 }); // 5 s after it ended

  // Another job (the fake Docker keeps the container running): closed by its button.
  await page.getByRole("button", { name: "Arrêter", exact: true }).click();
  const again = toasts.getByRole("status", { name: "Arrêt" });
  await expect(again).toBeVisible();
  await again.getByRole("button", { name: "Fermer" }).click();
  await expect(again).toBeHidden();
});
