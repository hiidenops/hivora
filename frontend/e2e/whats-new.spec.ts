import { expect, test } from "./test";

import { PASSWORD, signIn } from "./helpers";

// The "what's new" pop-up: once per version and browser, its Markdown rendered; closed, it
// does not come back. A fresh context: the shared fixture marks it seen everywhere else.
test("what's new: shown once after sign-in, Markdown rendered, gone once closed", async ({ page, browser }) => {
  await signIn(page); // the admin's password set (the fixture's page: pop-up already seen)
  const context = await browser.newContext();
  const fresh = await context.newPage();
  await fresh.goto("/login/");
  await fresh.getByLabel("Identifiant", { exact: true }).fill("admin");
  await fresh.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await fresh.getByRole("button", { name: "Se connecter" }).click();

  const popup = fresh.getByRole("dialog", { name: /Nouveautés de Hivora \d+\.\d+\.\d+/ });
  await expect(popup).toBeVisible();
  await expect(popup.locator("img[src='/icon.svg']")).toBeVisible();
  await expect(popup.locator("strong").first()).toBeVisible(); // **bold** rendered
  await expect(popup.getByText(/\*\*/)).toHaveCount(0);
  await popup.getByRole("button", { name: "C'est noté" }).click();
  await expect(popup).toBeHidden();

  await fresh.reload();
  await expect(fresh.getByRole("heading", { name: "Applications" })).toBeVisible();
  await expect(fresh.getByRole("dialog")).toHaveCount(0);
  await context.close();
});

test("what's new: after several updates, every version's notes since the one seen", async ({ page, browser }) => {
  await signIn(page);
  const context = await browser.newContext();
  await context.addInitScript(() => {
    if (!sessionStorage.getItem("seeded")) {
      localStorage.setItem("hivora.whatsNew", "0.3.4"); // this browser last saw 0.3.4
      sessionStorage.setItem("seeded", "1");
    }
  });
  const fresh = await context.newPage();
  await fresh.goto("/login/");
  await fresh.getByLabel("Identifiant", { exact: true }).fill("admin");
  await fresh.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await fresh.getByRole("button", { name: "Se connecter" }).click();

  const popup = fresh.getByRole("dialog", { name: /Nouveautés depuis la version 0\.3\.4/ });
  await expect(popup).toBeVisible();
  for (const version of ["0.3.6", "0.3.5"]) await expect(popup.getByText(version, { exact: true })).toBeVisible();
  await expect(popup.getByText("0.3.4", { exact: true })).toHaveCount(0); // seen already
  await popup.getByRole("button", { name: "C'est noté" }).click();
  await fresh.reload();
  await expect(fresh.getByRole("heading", { name: "Applications" })).toBeVisible();
  await expect(fresh.getByRole("dialog")).toHaveCount(0);
  await context.close();
});
