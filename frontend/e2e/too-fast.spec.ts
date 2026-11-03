import { expect, test } from "./test";

import { deployNginx, signIn } from "./helpers";

// A button whose action runs shows a spinner and waits: clicking again sends nothing.
test("loading: a restart clicked twice is sent once", async ({ page }) => {
  await signIn(page);
  const { app } = await deployNginx(page, "Pressée", 8611);
  let sent = 0;
  await page.route(`**/api/v1/apps/${app.id}/restart`, async (route) => {
    sent += 1;
    await new Promise((r) => setTimeout(r, 1500)); // a slow server
    await route.continue();
  });

  await page.goto(`/app/?id=${app.id}`);
  const restart = page.getByRole("button", { name: "Redémarrer" }).first();
  await restart.click();
  await expect(restart).toHaveAttribute("aria-busy", "true");
  await expect(restart).toBeDisabled();
  await restart.click({ force: true }); // impatient
  await expect(restart).not.toHaveAttribute("aria-busy", "true", { timeout: 20_000 }); // the job ended
  expect(sent).toBe(1);
});
