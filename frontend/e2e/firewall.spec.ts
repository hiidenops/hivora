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
  // Banned from its row in a fail2ban jail (a host with two jails, sshd picked), then unbanned.
  let banned: string[] = [];
  const sent: unknown[] = [];
  await page.route(/\/api\/v1\/host-firewall\?fresh=true$/, async (route) => {
    const json = await (await route.fetch()).json();
    route.fulfill({ json: { ...json, fail2ban_installed: true, fail2ban_running: true, jails: [
      { name: "recidive", banned: [], total_banned: 0, failed: 0 },
      { name: "sshd", banned, total_banned: banned.length, failed: 0 },
    ] } });
  }); // prettier-ignore
  await page.route("**/api/v1/host-firewall/fail2ban/sshd", (route) => {
    const body = route.request().postDataJSON() as { ip: string; ban: boolean };
    sent.push(body);
    banned = body.ban ? [body.ip] : [];
    return route.fulfill({ json: { output: "" } });
  });
  await page.reload(); // the firewall's state read again, with the jails
  await expect(live.getByLabel("Jail pour bannir")).toHaveValue("sshd");
  await expect(live.getByText("pas l'accès aux apps publiées par Docker", { exact: false })).toBeVisible();
  page.once("dialog", (d) => {
    expect(d.message()).toContain("Bannir 203.0.113.24 dans la jail « sshd »");
    void d.accept();
  });
  await row.getByRole("button", { name: "Bannir 203.0.113.24" }).click();
  await expect(row).toContainText("Bannie (sshd)");
  await row.getByRole("button", { name: "Débannir 203.0.113.24" }).click();
  await expect(row.getByRole("button", { name: "Bannir 203.0.113.24" })).toBeVisible();
  expect(sent).toEqual([{ ip: "203.0.113.24", ban: true }, { ip: "203.0.113.24", ban: false }]);
  await page.unroute(/\/api\/v1\/host-firewall\?fresh=true$/);
  await page.unroute("**/api/v1/host-firewall/fail2ban/sshd");
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
