import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// The host firewall pages: the host agent turned on from the overview (after its warning), its
// tiles, then each section through the tabs; turned off again. The API agrees each time.
test("firewall: host agent turned on, sections, then off", async ({ page }) => {
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
  // What listens, as a host would answer: a Docker app (UFW bypassed) and a local service.
  await page.route("**/api/v1/host-firewall/listening", (route) =>
    route.fulfill({ json: [
      { protocol: "tcp", address: "0.0.0.0", port: 25565, process: "docker-proxy", app: "survie", ufw: "bypassed" },
      { protocol: "tcp", address: "127.0.0.1", port: 5432, process: "postgres", app: null, ufw: "local" },
    ] }),
  ); // prettier-ignore
  await toggle.click(); // controlled: it follows the API, not the click
  // The overview: each section at a glance, a link to its page.
  await expect(page.getByRole("link", { name: "UFW", exact: true })).toContainText("inactif");
  await expect(page.getByRole("link", { name: "UFW", exact: true })).toContainText("0 règle(s)");
  const exposed = page.getByRole("link", { name: "Ports exposés" });
  await expect(exposed).toContainText("1 joignable(s) de l'extérieur");
  await expect(exposed).toContainText("1 publié(s) par Docker, UFW sans effet");
  expect(await agent()).toBe(true);

  // Ports: what listens now (a badge each, filterable), the UFW rules, a new rule's dialog.
  const tabs = page.getByRole("navigation", { name: "Sections du pare-feu" });
  await tabs.getByRole("link", { name: "Ports (UFW)" }).click();
  await expect(page).toHaveURL(/\/firewall\/ports\/$/);
  const listening = page.getByRole("region", { name: "En écoute maintenant (en direct)" });
  await expect(listening.getByRole("row").filter({ hasText: "25565/tcp" })).toContainText("Oui, Docker contourne UFW");
  await expect(listening.getByRole("row").filter({ hasText: "5432/tcp" })).toContainText("Non, local seulement");
  await listening.getByRole("button", { name: "Joignables seulement" }).click();
  await expect(listening.getByText("5432/tcp")).toBeHidden();
  const rules = page.getByRole("region", { name: "Règles UFW" });
  await expect(rules.getByRole("switch", { name: "UFW actif" })).not.toBeChecked();
  await expect(rules.getByText("Aucune règle.")).toBeVisible();
  await rules.getByRole("button", { name: "Nouvelle règle" }).click();
  await expect(page.getByRole("dialog", { name: "Nouvelle règle" }).getByRole("button", { name: "Ajouter la règle" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.unroute("**/api/v1/host-firewall/listening");

  // fail2ban and routes, each on its page; the side menu lists them too.
  await tabs.getByRole("link", { name: "fail2ban" }).click();
  await expect(page.getByRole("heading", { name: "fail2ban", level: 3 })).toBeVisible();
  await page.locator("aside").getByRole("link", { name: "Routes" }).click();
  await expect(page.getByRole("heading", { name: "Routes de l'hôte (lecture seule)", level: 3 })).toBeVisible();
  // Static routes (the e2e host's table: LAN 192.168.1.0/24 on eth0): one added, confirmed,
  // set by a job; one over the LAN refused (said, what was typed kept); removed.
  const statics = page.getByRole("region", { name: "Routes statiques" });
  await expect(statics.getByText("Aucune route statique.")).toBeVisible();
  const routeForm = statics; // the add row: its fields under the table's columns
  await routeForm.getByLabel("Destination").fill("10.8.0.5/24");
  await routeForm.getByLabel("Passerelle").fill("192.168.1.254");
  await routeForm.getByLabel("Interface").selectOption("eth0");
  await routeForm.getByLabel("Note").fill("VPN du bureau");
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Ajouter la route vers 10.8.0.5/24 via 192.168.1.254 ?");
    void d.accept();
  });
  await routeForm.getByRole("button", { name: "Ajouter une route" }).click();
  const routeRow = statics.getByRole("row").filter({ hasText: "10.8.0.0/24" }); // canonical
  await expect(routeRow).toContainText("Appliquée", { timeout: 20_000 }); // read again at the job's end
  await expect(routeRow).toContainText("192.168.1.254");
  await expect(routeRow).toContainText("eth0");
  await expect(routeRow).toContainText("VPN du bureau");
  await expect(routeForm.getByLabel("Destination")).toHaveValue("");
  await routeForm.getByLabel("Destination").fill("192.168.1.128/25");
  await routeForm.getByLabel("Passerelle").fill("192.168.1.254");
  page.once("dialog", (d) => void d.accept());
  await routeForm.getByRole("button", { name: "Ajouter une route" }).click();
  await expect(page.getByText("recouvre un réseau directement connecté", { exact: false })).toBeVisible();
  await expect(routeForm.getByLabel("Destination")).toHaveValue("192.168.1.128/25");
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Supprimer la route vers 10.8.0.0/24 (via 192.168.1.254) ?");
    void d.accept();
  });
  await routeRow.getByRole("button", { name: "Supprimer la route vers 10.8.0.0/24" }).click();
  await expect(statics.getByText("Aucune route statique.")).toBeVisible();
  await tabs.getByRole("link", { name: "Connexions" }).click();

  // Who is connected now, read every 3 s: none on the fake host, then an answer replaced.
  const live = page.getByRole("region", { name: "Connexions en cours" });
  await expect(live.getByText("Aucune connexion entrante en ce moment.")).toBeVisible();
  await page.route("**/api/v1/host-firewall/connections", (route) =>
    route.fulfill({ json: { conntrack: false, connections: [
      { ip: "203.0.113.24", origin: "internet", connections: 2, first_seen: Date.now() / 1000 - 180, targets: [{ port: 25565, name: "survie" }] },
    ] } }),
  ); // prettier-ignore
  const row = live.getByRole("row").filter({ hasText: "203.0.113.24" });
  await expect(row).toContainText("Internet", { timeout: 10_000 }); // the next refresh
  await expect(row).toContainText("survie :25565");
  await expect(row).toContainText("il y a 3 min");
  // Blocked from its row (an Internet address: the plain confirmation), as a job in a pop-up;
  // the note says where it was seen. The real backend, the fake host agent.
  const blockedNow = async () =>
    ((await (await page.request.get("/api/v1/host-firewall/blocked")).json()) as { address: string; note: string }[]).map((b) => [b.address, b.note]);
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Bloquer 203.0.113.24 ?");
    expect(d.message()).toContain("ni les apps publiées par Docker");
    void d.accept();
  });
  await row.getByRole("button", { name: "Bloquer 203.0.113.24" }).click();
  const toasts = page.getByRole("region", { name: "Suivi des tâches" });
  await expect(toasts.getByRole("status", { name: "Pare-feu de l'hôte" }).last().getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await expect(row).toContainText("Bloquée");
  expect(await blockedNow()).toEqual([["203.0.113.24", "survie :25565"]]);

  // The Blocked tab: the list, an address by hand with a note, the host's own refused.
  await tabs.getByRole("link", { name: "Bloquées" }).click();
  const list = page.getByRole("region", { name: "Adresses bloquées" });
  await expect(list.getByRole("row").filter({ hasText: "203.0.113.24" })).toContainText("survie :25565");
  const form = list; // the add row: its fields under the table's columns
  const typed = form.getByLabel("Adresse IP à bloquer");
  await typed.fill("198.51.100.3");
  await form.getByLabel("Note").fill("scan de ports");
  page.once("dialog", (d) => void d.accept());
  await form.getByRole("button", { name: "Bloquer une adresse" }).click();
  await expect(list.getByRole("row").filter({ hasText: "198.51.100.3" })).toContainText("scan de ports");
  await expect(typed).toHaveValue(""); // accepted: emptied
  await typed.fill("192.168.1.30"); // the local network: stronger words (cancelled here)
  page.once("dialog", (d) => {
    expect(d.message()).toContain("est une adresse du réseau local");
    void d.dismiss();
  });
  await form.getByRole("button", { name: "Bloquer une adresse" }).click();
  await typed.fill("203.0.113.7"); // the host's public address (HIVORA_HOST_PUBLIC_IP)
  page.once("dialog", (d) => void d.accept());
  await form.getByRole("button", { name: "Bloquer une adresse" }).click();
  await expect(page.getByText("Adresse de cette machine ou d'un de ses conteneurs", { exact: false })).toBeVisible();
  await expect(typed).toHaveValue("203.0.113.7"); // refused: what was typed stays
  await list.getByRole("button", { name: "Débloquer 198.51.100.3" }).click();
  await expect(list.getByRole("row").filter({ hasText: "198.51.100.3" })).toHaveCount(0);
  expect(await blockedNow()).toEqual([["203.0.113.24", "survie :25565"]]);
  await tabs.getByRole("link", { name: "Vue d'ensemble" }).click();
  await expect(page.getByRole("link", { name: "Adresses bloquées" })).toContainText("1 adresse(s) bloquée(s)");
  await expect(page.getByLabel("Routes", { exact: true })).toContainText("0 route(s) statique(s)"); // the tile; removed above

  // Unblocked from its row.
  await tabs.getByRole("link", { name: "Connexions" }).click();
  await row.getByRole("button", { name: "Débloquer 203.0.113.24" }).click();
  await expect(row.getByRole("button", { name: "Bloquer 203.0.113.24" })).toBeVisible({ timeout: 10_000 });
  expect(await blockedNow()).toEqual([]);
  await expect(live.getByText("conntrack n'est pas installé", { exact: false })).toBeVisible(); // apps unseen
  // Installed on request: confirmed, then a job followed in a pop-up.
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Installer le paquet conntrack");
    void d.accept();
  });
  await live.getByRole("button", { name: "Installer conntrack" }).click();
  const job = page.getByRole("region", { name: "Suivi des tâches" }).getByRole("status", { name: "Installation d'un paquet sur la machine" });
  await expect(job.getByText("Réussi")).toBeVisible({ timeout: 20_000 });
  await page.unroute("**/api/v1/host-firewall/connections");

  await tabs.getByRole("link", { name: "Vue d'ensemble" }).click();
  await toggle.click(); // no warning to turn it off
  await expect(page.getByRole("link", { name: "Ports exposés" })).toBeHidden();
  await expect.poll(agent).toBe(false);
});
