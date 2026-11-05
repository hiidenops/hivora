"use client";

import { Activity, Ban, Boxes, BrickWall, ChevronDown, Container, FileCode, Globe, LayoutDashboard, LayoutGrid, LogOut, Menu, Network, Route, Search, Server, Settings, Share2, ShieldBan, ShieldCheck, Users, Waypoints } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { SystemAlerts, needsAttention } from "@/features/system/system-alerts";
import { ApiError, api, type Me, type Role } from "@/lib/api/client";
import { useLogout, useMe, useReleases, useSystemStatus } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { readPref, writePref } from "@/lib/prefs";
import { RealtimeProvider, useConnected } from "@/lib/realtime";
import { cn } from "@/lib/utils";

import { Brand } from "./brand";
import { JobToasts } from "./job-toasts";
import { ShelfCat } from "./shelf-cat";

// Loaded once the panel is open: the notes pop-up of a new version.
// Opened with Ctrl+K (or "/"): loaded the first time only.
const CommandPalette = dynamic(() => import("./command-palette").then((m) => m.CommandPalette), { ssr: false });
const WhatsNew = dynamic(() => import("@/features/system/whats-new").then((m) => m.WhatsNew), { ssr: false });

const LEVEL: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

interface Session {
  me: Me;
  can: (role: Role) => boolean;
  advanced: boolean;
  setAdvanced: (value: boolean) => void;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside AppShell");
  return ctx;
}

type Entry = { href: string; label: MessageKey; icon: typeof LayoutGrid };

/** The firewall's pages: its tabs, and its entries in the side menu while it is open. */
export const FIREWALL_TABS: Entry[] = [
  { href: "/firewall/", label: "fw.tab.overview", icon: LayoutDashboard },
  { href: "/firewall/ports/", label: "fw.tab.ports", icon: ShieldCheck },
  { href: "/firewall/blocked/", label: "fw.tab.blocked", icon: ShieldBan },
  { href: "/firewall/fail2ban/", label: "fw.tab.fail2ban", icon: Ban },
  { href: "/firewall/routes/", label: "fw.tab.routes", icon: Route },
];

type NavItem = Entry & { role: Role; also?: string[]; sub?: Entry[] };
// `tone`: the group's hue (--g), for its header, edge and active bar.
type NavGroup = { key: string; label: MessageKey; tone: string; items: NavItem[] };

// The side menu, grouped. `also`: other paths under that entry (a site's page belongs to Sites);
// `sub`: its pages, listed under it while one is open (wide screens). System is the
// Administration group's last entry, drawn with its dot (SystemLink).
export const NAV_HOME: NavItem = { href: "/", label: "nav.dashboard", icon: LayoutGrid, role: "viewer", also: ["/app/", "/edit/"] };
export const NAV_GROUPS: NavGroup[] = [
  {
    key: "apps",
    label: "nav.group.apps",
    tone: "[--g:var(--nav-apps)]",
    items: [
      { href: "/catalog/", label: "nav.catalog", icon: Boxes, role: "viewer", also: ["/deploy/"] },
      { href: "/custom/", label: "custom.title", icon: Container, role: "operator" },
      { href: "/python/", label: "py.title", icon: FileCode, role: "operator" },
      { href: "/sites/", label: "nav.sites", icon: Globe, role: "viewer", also: ["/app/site/", "/site/"] },
    ],
  },
  {
    key: "network",
    label: "nav.group.network",
    tone: "[--g:var(--nav-network)]",
    items: [
      { href: "/zones/", label: "nav.zones", icon: Network, role: "viewer" },
      { href: "/topology/", label: "nav.topology", icon: Share2, role: "viewer" },
      { href: "/addressing/", label: "nav.addressing", icon: Waypoints, role: "viewer" },
      { href: "/firewall/", label: "nav.firewall", icon: BrickWall, role: "admin", sub: FIREWALL_TABS },
    ],
  },
  {
    key: "admin",
    label: "nav.group.admin",
    tone: "[--g:var(--nav-admin)]",
    items: [
      { href: "/activity/", label: "nav.activity", icon: Activity, role: "viewer" },
      { href: "/users/", label: "nav.users", icon: Users, role: "admin" },
      { href: "/settings/", label: "nav.settings", icon: Settings, role: "viewer" },
      { href: "/system/", label: "nav.system", icon: Server, role: "viewer" },
    ],
  },
];

/** The entry the current page belongs to: the longest matching path. */
function activeHref(pathname: string): string {
  let best = "/";
  let len = pathname === "/" ? 1 : 0;
  for (const n of [NAV_HOME, ...NAV_GROUPS.flatMap((g) => g.items)]) {
    for (const p of n.href === "/" ? (n.also ?? []) : [n.href, ...(n.also ?? [])]) {
      if (pathname.startsWith(p) && p.length > len) [best, len] = [n.href, p.length];
    }
  }
  return best;
}

const DOT = {
  error: { label: "system.dotError", color: "bg-danger" },
  warn: { label: "system.dotWarn", color: "bg-warn" },
  update: { label: "system.dotUpdate", color: "bg-info" },
} as const;

function ConnectionDot() {
  const { t } = useI18n();
  const connected = useConnected();
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("size-2 rounded-full", connected ? "bg-ok" : "bg-idle")} />
      {connected ? t("common.live") : t("common.offline")}
    </span>
  );
}

/** Authenticated layout: redirects to login / forced password change, then renders the panel. */
export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me, error, isPending } = useMe();
  // No TOTP: one guarded request tells whether this panel requires it (public); held on
  // the spinner meanwhile, so nothing of the panel shows before /setup-totp/.
  const probe = useQuery({
    queryKey: ["totp-probe", me?.id],
    queryFn: () => api<unknown>("/auth/sessions"),
    enabled: !!me && !me.must_change_password && !me.totp_enabled,
    retry: false,
  });
  const totpSetup = probe.error instanceof ApiError && probe.error.code === "totp_setup_required";
  const held = !!me && !me.totp_enabled && (probe.isPending || totpSetup);
  // Admins: the System checks (the System button dot, the exposure banner), once the panel is open.
  const ready = !!me && !me.must_change_password && (me.totp_enabled || probe.isSuccess);
  const { data: status } = useSystemStatus(ready && me?.role === "admin");
  const { data: releases } = useReleases(ready && me?.role === "admin");
  // Health first (orange, red); otherwise a newer version (blue).
  const attention = needsAttention(status) ?? (releases?.newer ? "update" : null);
  const logout = useLogout();
  const qc = useQueryClient();
  // Every click in the navigation asks the server again for the available version (it reads
  // GitHub at most every 20 minutes): a new release shows on the System button soon.
  const checkUpdates = () => {
    if (me?.role === "admin") void qc.invalidateQueries({ queryKey: ["system-releases"] });
  };
  const [advanced, setAdvancedState] = useState(false);
  const [palette, setPalette] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  useEffect(() => setMobileNav(false), [pathname]);
  // Ctrl+K / ⌘K anywhere, "/" outside a text field: the search palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || !!el.closest(".cm-editor, .xterm"));
      if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") || (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey)) {
        e.preventDefault();
        setPalette((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => setAdvancedState(readPref("advanced") === "1"), []);
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login/");
    else if (me?.must_change_password) router.replace("/change-password/");
    else if (totpSetup) router.replace("/setup-totp/");
  }, [error, me, router, totpSetup]);

  if (isPending || !me || me.must_change_password || held) {
    return (
      <div className="grid min-h-screen place-items-center">
        <div role="status" aria-label={t("common.loading")} className="size-10 animate-spin rounded-full border-4 border-muted border-t-primary" />
      </div>
    );
  }

  const session: Session = {
    me,
    can: (role) => LEVEL[me.role] >= LEVEL[role],
    advanced,
    setAdvanced: (value) => {
      writePref("advanced", value ? "1" : "0");
      setAdvancedState(value);
    },
  };

  const footer = (
    <>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={advanced} onChange={(e) => session.setAdvanced(e.target.checked)} />
        {t("nav.advanced")}
      </label>
      <div className="flex items-center gap-3 text-sm">
        <span className="truncate font-medium">{me.username}</span>
        <span className="mr-auto">
          <ConnectionDot />
        </span>
        <button
          className="text-muted-foreground hover:text-foreground"
          aria-label={t("nav.logout")}
          title={t("nav.logout")}
          disabled={logout.isPending}
          onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login/") })}
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </>
  );

  return (
    <SessionContext.Provider value={session}>
      <RealtimeProvider enabled>
        {/* Above <main>, keyed by page: a job's pop-up stays when the page changes. */}
        <JobToasts>
          <WhatsNew />
          {palette && <CommandPalette onClose={() => setPalette(false)} />}
          <div className="flex min-h-screen flex-col md:flex-row">
            <aside className="relative z-10 flex shrink-0 flex-col gap-1 border-b bg-sidebar p-3 shadow-md md:sticky md:top-0 md:h-screen md:w-56 md:overflow-x-hidden md:overflow-y-auto md:border-b-0 md:border-r">
              {/* The logo centred; its buttons on the right, out of the centring. */}
              <div className="relative mb-1 flex items-center justify-center">
                <Link href="/" aria-label={t("app.name")} className="rounded-md px-2 py-1">
                  <Brand />
                </Link>
                <div className="absolute right-0 flex items-center gap-2">
                  <SearchButton onClick={() => setPalette(true)} />
                  <Sheet open={mobileNav} onOpenChange={setMobileNav}>
                    <SheetTrigger asChild>
                      <Button variant="outline" size="sm" className="md:hidden" aria-label={t("nav.menu")}>
                        <Menu />
                      </Button>
                    </SheetTrigger>
                    <SheetContent title={t("nav.menu")} closeLabel={t("common.close")} resizeLabel={t("common.resize")} widthKey="nav">
                      <NavTree pathname={pathname} can={session.can} attention={attention} onNavigate={checkUpdates} />
                      <div className="mt-6 grid gap-3 border-t pt-4">{footer}</div>
                    </SheetContent>
                  </Sheet>
                </div>
              </div>
              <div className="hidden md:block">
                <NavTree pathname={pathname} can={session.can} attention={attention} onNavigate={checkUpdates} />
              </div>
              <div className="mt-auto hidden flex-col gap-2 px-2 pt-3 md:flex">
                <ShelfCat />
                {footer}
              </div>
            </aside>
            <main key={pathname} className="animate-enter min-w-0 flex-1 p-4 md:p-8">
              <SystemAlerts status={status} />
              {children}
            </main>
          </div>
        </JobToasts>
      </RealtimeProvider>
    </SessionContext.Provider>
  );
}

export function PageHeader({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const LINK = "relative flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-2 py-1 text-sm transition-[background-color,color,box-shadow,translate] duration-200 ease-(--ease-out)";
const LINK_ON = "surface font-medium before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-(--g,var(--primary))";
const LINK_OFF = "text-muted-foreground hover:translate-x-0.5 hover:bg-muted hover:text-foreground";

/** Opens the search palette (its shortcut in the tooltip). */
function SearchButton({ onClick }: { onClick: () => void }) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("palette.open")}
      title={t("palette.open")}
      className="grid size-8 shrink-0 place-items-center rounded-md border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <Search className="size-4" />
    </button>
  );
}

/** The side menu: the dashboard, then the groups, each folding (remembered in this
 *  browser); the group of the current page is always open. */
function NavTree({ pathname, can, attention, onNavigate }: {
  pathname: string;
  can: (role: Role) => boolean;
  attention: keyof typeof DOT | null;
  onNavigate: () => void;
}) {
  const { t } = useI18n();
  const current = activeHref(pathname);
  // Only drawn once signed in (never prerendered): the browser's preferences are there.
  const [folded, setFolded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(NAV_GROUPS.map((g) => [g.key, readPref(`fold.nav.${g.key}`) === "1"])),
  );
  // Arriving on a page of a folded group (search, breadcrumb, a link) opens that group;
  // it can be folded again while there.
  const home = NAV_GROUPS.find((g) => g.items.some((n) => n.href === current))?.key;
  useEffect(() => {
    if (!home) return;
    writePref(`fold.nav.${home}`, "0");
    setFolded((f) => (f[home] ? { ...f, [home]: false } : f));
  }, [home, current]);
  const toggle = (key: string) =>
    setFolded((f) => {
      writePref(`fold.nav.${key}`, f[key] ? "0" : "1");
      return { ...f, [key]: !f[key] };
    });

  const link = (n: NavItem) => {
    const active = n.href === current;
    if (n.href === "/system/") return <SystemLink key={n.href} active={active} attention={attention} onClick={onNavigate} />;
    return (
      <Fragment key={n.href}>
        <Link href={n.href} onClick={onNavigate} className={cn(LINK, active ? LINK_ON : LINK_OFF)}>
          <n.icon className="size-4 shrink-0" /> {t(n.label)}
        </Link>
        {active && n.sub && (
          <div className="ml-4 flex flex-col gap-0.5 border-l pl-2">
            {n.sub.map((e) => (
              <Link
                key={e.href}
                href={e.href}
                onClick={onNavigate}
                aria-current={pathname === e.href ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1 text-xs transition-colors",
                  pathname === e.href ? "font-medium text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <e.icon className="size-3.5 shrink-0" /> {t(e.label)}
              </Link>
            ))}
          </div>
        )}
      </Fragment>
    );
  };

  return (
    <nav aria-label={t("nav.menu")} className="flex flex-col gap-1">
      {link(NAV_HOME)}
      {NAV_GROUPS.map((g) => {
        const items = g.items.filter((n) => can(n.role));
        if (items.length === 0) return null;
        const open = !folded[g.key];
        const here = g.key === home;
        return (
          <div key={g.key} className={cn("mt-3 flex flex-col gap-0.5 rounded-md border-l-2 border-(--g) bg-(--g)/6 pl-1 shadow-[inset_0_1px_0_var(--highlight),var(--shadow-md)] ring-1 ring-(--g)/15", g.tone)}>
            <button
              type="button"
              aria-expanded={open}
              onClick={() => toggle(g.key)}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider transition-colors hover:bg-muted hover:text-foreground hover:ring-1 hover:ring-border",
                open ? "text-(--g)" : "bg-(--g)/10 text-(--g)",
              )}
            >
              <ChevronDown className={cn("size-3.5 shrink-0 transition-transform duration-200", !open && "-rotate-90")} />
              <span className="mr-auto">{t(g.label)}</span>
              {/* Folded: how many pages it holds, and a dot when the open page is one of them. */}
              {!open && (
                <span className="flex items-center gap-1.5 font-mono normal-case tracking-normal">
                  {here && <span className="size-1.5 rounded-full bg-(--g)" />}
                  {items.length}
                </span>
              )}
            </button>
            {open && items.map(link)}
          </div>
        );
      })}
    </nav>
  );
}

/** The panel itself (version, health, updates): at the bottom of the navigation, with the
 *  dot that says something needs a look (health first, then a newer version). */
function SystemLink({ active, attention, onClick }: { active: boolean; attention: keyof typeof DOT | null; onClick: () => void }) {
  const { t } = useI18n();
  return (
    <Link
      href="/system/"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(LINK, active ? LINK_ON : LINK_OFF)}
    >
      <Server className="size-4 shrink-0" /> {t("nav.system")}
      {attention && (
        <span
          role="img"
          aria-label={t(DOT[attention].label)}
          title={t(DOT[attention].label)}
          className={cn("ml-auto size-2 shrink-0 rounded-full", DOT[attention].color)}
        />
      )}
    </Link>
  );
}
