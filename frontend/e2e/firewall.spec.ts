import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// The host firewall page: the host agent turned on (after its warning), its UFW section shown
// (inactive, no rule on the fake host), then turned off again. The API agrees each time.
test("firewall: host agent turned on, then off", async ({ page }) => {
  await signIn(page);
  const agent = async () => (await (await page.request.get("/api/v1/host-firewall")).json()).agent;

  await page.getByRole("link", { name: "Pare-feu", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pare-feu", level: 1 })).toBeVisible();
  const toggle = page.getByRole("switch", { name: "Agent hôte (UFW, fail2ban)" });
  await expect(toggle).not.toBeChecked();
  expect(await agent()).toBe(false);

  page.once("dialog", (d) => {
    expect(d.message()).toContain("Activer l'agent hôte ?");
    void d.accept();
  });
  await toggle.click(); // controlled: it follows the API, not the click
  await expect(page.getByRole("heading", { name: "UFW", level: 3 })).toBeVisible();
  await expect(page.getByRole("switch", { name: "UFW actif" })).not.toBeChecked();
  await expect(page.getByText("Aucune règle.")).toBeVisible();
  expect(await agent()).toBe(true);

  await toggle.click(); // no warning to turn it off
  await expect(page.getByRole("heading", { name: "UFW", level: 3 })).toBeHidden();
  await expect.poll(agent).toBe(false);
});
