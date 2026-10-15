import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import { PASSWORD } from "./helpers";
import { HOST, PUBLIC_PORT } from "./host";

// A panel reachable from the Internet (its own server, HIVORA_ACCESS=public): after the
// first password change, TOTP must be set up before anything else; the session goes on.
test.use({ baseURL: `http://${HOST}:${PUBLIC_PORT}` });

/** The current RFC 6238 code of a base32 secret (what an authenticator app shows). */
function totp(secret: string, at = Date.now()) {
  let bits = "";
  for (const c of secret.replace(/=+$/, "")) bits += "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567".indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const mac = createHmac("sha1", key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

test("public panel: TOTP is set up before anything else", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill("admin");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.getByLabel("Mot de passe actuel", { exact: true }).fill("admin");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Enregistrer" }).click();

  await expect(page).toHaveURL(/\/setup-totp\/$/);
  await expect(page.getByText("Double authentification obligatoire")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeHidden();
  const blocked = await page.request.get("/api/v1/apps");
  expect(blocked.status()).toBe(403);
  expect((await blocked.json()).error.code).toBe("totp_setup_required");

  await page.getByRole("button", { name: "Activer" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Code à 6 chiffres", { exact: true }).fill(totp(secret));
  await page.getByRole("button", { name: "Vérifier" }).click();
  const recovery = (await page.locator("pre").first().textContent())!.trim().split("\n");
  expect(recovery.length).toBe(10);
  await expect(page.getByRole("button", { name: "Désactiver" })).toBeHidden(); // forced: no way back
  await page.getByRole("button", { name: "J'ai noté mes codes, continuer" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible(); // same session

  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const off = await page.request.post("/api/v1/auth/totp/disable", {
    headers: { "X-CSRF-Token": csrf_token }, data: { password: PASSWORD },
  }); // prettier-ignore
  expect(off.status()).toBe(409);
  expect((await off.json()).error.code).toBe("totp_mandatory");

  // Signed in again: the code is asked for (a recovery code here, the TOTP one is used up).
  await page.request.post("/api/v1/auth/logout", { headers: { "X-CSRF-Token": csrf_token } });
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.getByLabel("Code de vérification (ou code de récupération)").fill(recovery[0]);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
});
