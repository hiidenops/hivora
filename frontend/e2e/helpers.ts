import { expect, type Browser, type Page } from "@playwright/test";

// What every e2e file shares. Each file runs alone too: `signIn` sets the admin's password
// if no test did yet (only the first-start test needs a fresh instance, as `npm run e2e`
// always gives it).

export const PASSWORD = "correct-horse-battery";

/** Signed in as admin, whatever ran before: the forced first password change is done here
 *  through the API if no earlier test did it. */
export async function signIn(page: Page) {
  const login = (password: string) => page.request.post("/api/v1/auth/login", { data: { username: "admin", password } });
  if (!(await login(PASSWORD)).ok()) {
    const first = await login("admin");
    expect(first.ok()).toBe(true);
    const changed = await page.request.post("/api/v1/auth/password", {
      headers: { "X-CSRF-Token": (await first.json()).csrf_token },
      data: { current: "admin", new: PASSWORD },
    });
    expect(changed.ok()).toBe(true);
  }
  await page.goto("/login/");
  await page.getByLabel("Identifiant", { exact: true }).fill("admin");
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
}

/** The signed-in admin's CSRF header, and a wait for a job to succeed (20 s at most). */
export async function adminApi(page: Page) {
  const { csrf_token } = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = { "X-CSRF-Token": csrf_token as string };
  const done = async (id: number) =>
    expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${id}`)).json()).status, {
      timeout: 20_000,
    }).toBe("succeeded");
  return { headers, done };
}

/** An nginx from the catalog, deployed through the API (its job waited for). */
export async function deployNginx(page: Page, name: string, port: number) {
  const { headers, done } = await adminApi(page);
  const created = await (await page.request.post("/api/v1/apps", {
    headers, data: { template: "nginx", name, inputs: { web_port: port } },
  })).json(); // prettier-ignore
  await done(created.job.id);
  return created as { app: { id: number }; job: { id: number } };
}

/** A viewer account created by the admin, signed in on a new page (its first password
 *  change done). */
export async function signInViewer(page: Page, browser: Browser, username: string) {
  const { headers } = await adminApi(page);
  await page.request.post("/api/v1/users", {
    headers, data: { username, role: "viewer", password: "temporary-pass-1" },
  }); // prettier-ignore
  const viewer = await browser.newPage();
  await viewer.goto("/login/");
  await viewer.getByLabel("Identifiant", { exact: true }).fill(username);
  await viewer.getByLabel("Mot de passe", { exact: true }).fill("temporary-pass-1");
  await viewer.getByRole("button", { name: "Se connecter" }).click();
  await viewer.getByLabel("Mot de passe actuel", { exact: true }).fill("temporary-pass-1");
  await viewer.getByLabel("Nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByLabel("Confirmer le nouveau mot de passe", { exact: true }).fill(PASSWORD);
  await viewer.getByRole("button", { name: "Enregistrer" }).click();
  await expect(viewer.getByRole("heading", { name: "Applications" })).toBeVisible();
  return viewer;
}

/** Everything clickable on the page shows the hand (disabled controls excepted). */
export async function expectPointerCursors(page: Page) {
  const arrows = await page.$$eval(
    "button:not(:disabled), a[href], select:not(:disabled), [role=tab], [role=switch]:not(:disabled), summary",
    (els) =>
      els
        .filter((e) => getComputedStyle(e).cursor !== "pointer")
        .map((e) => `${e.tagName} ${(e.textContent || e.getAttribute("aria-label") || "").trim().slice(0, 40)}`),
  );
  expect(arrows).toEqual([]);
}

/** An entry of the app page's round menu (zone, edit, backups, tasks, logs, console, removal…). */
export async function openAppMenu(page: Page, item: string) {
  await page.getByRole("button", { name: "Menu de l'application" }).click();
  await page.getByRole("menuitem", { name: item, exact: true }).click();
}
