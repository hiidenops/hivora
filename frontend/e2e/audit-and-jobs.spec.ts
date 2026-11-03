import { expect, test } from "./test";

import { signIn } from "./helpers";

// Activity: 10 jobs and 10 log entries by default, then 20, 50 or all of them (asked again
// from the server with that limit).
test("activity: 10 rows by default, then 20, 50 or all, for the jobs and the log", async ({ page }) => {
  await signIn(page);
  const asked = (path: string, limit: number) =>
    page.waitForRequest((r) => new URL(r.url()).pathname === `/api/v1/${path}` && new URL(r.url()).searchParams.get("limit") === String(limit));
  const first = Promise.all([asked("jobs", 10), asked("audit", 10)]);
  await page.goto("/activity/");
  await first;
  const jobs = page.getByLabel("Nombre de tâches affichées");
  const audit = page.getByLabel("Nombre d'entrées du journal affichées");
  await expect(jobs).toHaveValue("10");
  await expect(audit).toHaveValue("10");
  const rows = page.locator("table").last().locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeLessThanOrEqual(10);

  let next = asked("jobs", 20);
  await jobs.selectOption("20");
  await next;
  next = asked("jobs", 500);
  await jobs.selectOption({ label: "Tout" });
  await next;
  next = asked("audit", 50);
  await audit.selectOption("50");
  await next;
  await expect(audit).toHaveValue("50");
});
