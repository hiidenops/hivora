import { expect, test } from "@playwright/test";

import { adminApi, deployNginx, signIn } from "./helpers";

// The app -> sites model through the API only: an nginx from the catalog starts hosting,
// an added site on its own port, then off and removed.
test("hosted sites API: list, plan, add, edit a file, turn off, remove", async ({ page }) => {
  await signIn(page);
  const { headers, done } = await adminApi(page);

  const created = await deployNginx(page, "Annexe", 8200);
  const app = created.app.id;
  const hosting = await page.request.post(`/api/v1/apps/${app}/sites/hosting`, { headers });
  expect(hosting.status()).toBe(200);
  const host = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(host.sites.map((s: { slug: string; main: boolean }) => [s.slug, s.main])).toEqual([["main", true]]);

  const site = { name: "Docs", port: 8201 };
  const plan = await (await page.request.post(`/api/v1/apps/${app}/sites/plan`, { headers, data: site })).json();
  expect([plan.recreate, plan.ports_after]).toEqual([true, [8201]]);
  const added = await page.request.post(`/api/v1/apps/${app}/sites`, { headers, data: site });
  expect(added.status()).toBe(202);
  const change = await added.json();
  expect([change.job.kind, change.config_job.kind]).toEqual(["update", "site_config"]);
  await done(change.job.id);
  await done(change.config_job.id);
  const listed = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(listed.sites.map((s: { slug: string; port: number }) => [s.slug, s.port])).toEqual([["main", 8200], ["docs", 8201]]);

  const docs = change.site.id;
  // The added site's own files: one created, then read back.
  const saved = await page.request.put(`/api/v1/apps/${app}/sites/${docs}/files/content`, {
    headers, data: { path: "index.html", content: "<h1>Docs</h1>", base_sha256: null },
  }); // prettier-ignore
  expect(saved.status()).toBe(202);
  await done((await saved.json()).id);
  const files = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/files`)).json();
  expect(files.files.map((f: { path: string }) => f.path)).toEqual(["index.html"]);
  const read = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/files/content?path=index.html`)).json();
  expect(read.content).toBe("<h1>Docs</h1>");
  const off = await page.request.put(`/api/v1/apps/${app}/sites/${docs}/enabled`, { headers, data: { enabled: false } });
  expect(off.status()).toBe(202);
  await done((await off.json()).id);
  const removal = await (await page.request.get(`/api/v1/apps/${app}/sites/${docs}/removal-plan`)).json();
  expect(removal.ports_after).toEqual([]);
  const gone = await page.request.delete(`/api/v1/apps/${app}/sites/${docs}`, { headers });
  expect(gone.status()).toBe(202);
  await done((await gone.json()).job.id);
  const after = await (await page.request.get(`/api/v1/apps/${app}/sites`)).json();
  expect(after.sites.map((s: { slug: string }) => s.slug)).toEqual(["main"]);
});
