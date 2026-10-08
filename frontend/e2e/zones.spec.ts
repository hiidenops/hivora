import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

type Zone = { slug: string; name: string; network_mode: string };

// The zones page: a zone created with its network mode (the API agrees), then removed.
test("zones: create a linked zone, then remove it", async ({ page }) => {
  await signIn(page);
  const zones = async () => ((await (await page.request.get("/api/v1/zones")).json()) as Zone[]).filter((z) => z.name === "Labo");

  await page.getByRole("link", { name: "Zones", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Zones", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "Nouvelle zone" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill("Labo");
  await dialog.getByRole("radio", { name: /Reliées entre elles/ }).check();
  await dialog.getByRole("button", { name: "Nouvelle zone" }).click();
  await expect(dialog).toBeHidden();

  const card = page.getByRole("article", { name: "Labo" });
  await expect(card.getByText("Reliées entre elles")).toBeVisible();
  await expect(card.getByText("Aucune application dans cette zone.")).toBeVisible();
  await expect.poll(async () => (await zones()).map((z) => z.network_mode)).toEqual(["shared"]);

  page.once("dialog", (d) => {
    expect(d.message()).toBe("Supprimer la zone « Labo » ?");
    void d.accept();
  });
  await card.getByRole("button", { name: "Supprimer" }).click();
  await expect(card).toHaveCount(0);
  await expect.poll(zones).toEqual([]);
});
