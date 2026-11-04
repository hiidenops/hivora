import { expect, test } from "./test";

import { deployNginx, signIn } from "./helpers";

// Getting around: Ctrl+K to an app and to a page, a menu group folded then opened again,
// the app page's breadcrumb, a job's link to its app.
test("navigation: palette, menu groups, breadcrumb, job to app", async ({ page }) => {
  await signIn(page);
  const { app } = await deployNginx(page, "Boussole", 8380);
  await page.reload();

  // Palette: an app by a few letters (case and accents ignored), Enter opens its page.
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Aller à…" });
  await palette.getByRole("combobox").fill("bouss");
  await expect(palette.getByRole("option", { name: /Boussole/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/app/\\?id=${app.id}$`));
  await expect(page.getByRole("heading", { name: "Boussole", level: 1 })).toBeVisible();

  // Breadcrumb: back to the dashboard.
  const crumbs = page.getByRole("navigation", { name: "Fil d'Ariane" });
  await expect(crumbs.getByText("Boussole")).toHaveAttribute("aria-current", "page");
  await crumbs.getByRole("link", { name: "Tableau de bord" }).click();
  await expect(page).toHaveURL(/\/$/);

  // Palette: a page, from its name without accent; "/" opens it too.
  await page.keyboard.press("/");
  await palette.getByRole("combobox").fill("activite");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Activité", level: 1 })).toBeVisible();

  // Menu group: folded (its links gone, remembered after a reload), then opened again.
  const menu = page.getByRole("complementary").getByRole("navigation", { name: "Menu" });
  const network = menu.getByRole("button", { name: /Réseau/ });
  await expect(network).toHaveAttribute("aria-expanded", "true");
  await network.click();
  await expect(menu.getByRole("link", { name: "Topologie" })).toBeHidden();
  await page.reload();
  await expect(menu.getByRole("link", { name: "Topologie" })).toBeHidden();
  await network.click();
  await expect(menu.getByRole("link", { name: "Topologie" })).toBeVisible();
  // The group of the current page folds too (Activity, under Administration)...
  const admin = menu.getByRole("button", { name: /Administration/ });
  await admin.click();
  await expect(menu.getByRole("link", { name: "Activité" })).toBeHidden();
  // ... and opens again when one of its pages is reached another way.
  await page.goto("/users/");
  await expect(admin).toHaveAttribute("aria-expanded", "true");
  await page.goto("/activity/");

  // A job of the app: one click to its page.
  await page.getByRole("button", { name: /Boussole|boussole/ }).first().click();
  await page.getByRole("link", { name: "Ouvrir l'app Boussole" }).click();
  await expect(page.getByRole("heading", { name: "Boussole", level: 1 })).toBeVisible();
});
