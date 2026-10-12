"use client";

import { Activity, Ban, Boxes, BrickWall, Globe, LayoutDashboard, LayoutGrid, LogOut, Network, Route, Settings, Share2, ShieldBan, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { Switch } from "@/components/ui/input";
import { ApiError, type Me, type Role } from "@/lib/api/client";
import { useLogout, useMe } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { readPref, writePref } from "@/lib/prefs";
import { RealtimeProvider, useConnected } from "@/lib/realtime";
import { cn } from "@/lib/utils";

import { Brand } from "./brand";
import { JobToasts } from "./job-toasts";
import { ShelfCat } from "./shelf-cat";

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

// `also`: another path under that entry (a site's page belongs to Sites); `sub`: its pages,
// listed under it while one is open (wide screens).
const NAV: (Entry & { role: Role; also?: string; sub?: Entry[] })[] = [
  { href: "/", label: "nav.dashboard", icon: LayoutGrid, role: "viewer" },
  { href: "/catalog/", label: "nav.catalog", icon: Boxes, role: "viewer" },
  { href: "/sites/", label: "nav.sites", icon: Globe, role: "viewer", also: "/app/site/" },
  { href: "/zones/", label: "nav.zones", icon: Network, role: "viewer" },
  { href: "/topology/", label: "nav.topology", icon: Share2, role: "viewer" },
  { href: "/activity/", label: "nav.activity", icon: Activity, role: "viewer" },
  { href: "/firewall/", label: "nav.firewall", icon: BrickWall, role: "admin", sub: FIREWALL_TABS },
  { href: "/users/", label: "nav.users", icon: Users, role: "admin" },
  { href: "/settings/", label: "nav.settings", icon: Settings, role: "viewer" },
];

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
  const logout = useLogout();
  const [advanced, setAdvancedState] = useState(false);

  useEffect(() => setAdvancedState(readPref("advanced") === "1"), []);
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login/");
    else if (me?.must_change_password) router.replace("/change-password/");
  }, [error, me, router]);

  if (isPending || !me || me.must_change_password) {
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

  return (
    <SessionContext.Provider value={session}>
      <RealtimeProvider enabled>
        {/* Above <main>, keyed by page: a job's pop-up stays when the page changes. */}
        <JobToasts>
          <div className="flex min-h-screen flex-col md:flex-row">
            <aside className="relative z-10 flex shrink-0 flex-col gap-1 border-b bg-sidebar p-3 shadow-md md:sticky md:top-0 md:h-screen md:w-56 md:overflow-x-hidden md:overflow-y-auto md:border-b-0 md:border-r">
              <Link href="/" aria-label={t("app.name")} className="mb-4 rounded-md px-2 py-3">
                <Brand />
              </Link>
              <nav className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
                {NAV.filter((n) => session.can(n.role)).map((n) => {
                  const active =
                    n.href === "/" ? pathname === "/" : pathname.startsWith(n.href) || (!!n.also && pathname.startsWith(n.also));
                  return (
                    <Fragment key={n.href}>
                      <Link
                        href={n.href}
                        className={cn(
                          "relative flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-2 py-1.5 text-sm transition-[background-color,color,box-shadow,translate] duration-200 ease-(--ease-out)",
                          active
                            ? "surface font-medium before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-primary"
                            : "text-muted-foreground hover:translate-x-0.5 hover:bg-muted hover:text-foreground",
                        )}
                      >
                        <n.icon className="size-4 shrink-0" /> {t(n.label)}
                      </Link>
                      {active && n.sub && (
                        <div className="ml-4 hidden flex-col gap-0.5 border-l pl-2 md:flex">
                          {n.sub.map((e) => (
                            <Link
                              key={e.href}
                              href={e.href}
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
                })}
              </nav>
              <div className="mt-auto hidden flex-col gap-3 px-2 pt-6 md:flex">
                <ShelfCat />
                <label className="flex items-center gap-2 text-sm">
                  <Switch checked={advanced} onChange={(e) => session.setAdvanced(e.target.checked)} />
                  {t("nav.advanced")}
                </label>
                <ConnectionDot />
                <div className="flex items-center justify-between text-sm">
                  <span className="truncate font-medium">{me.username}</span>
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={t("nav.logout")}
                    title={t("nav.logout")}
                    onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login/") })}
                  >
                    <LogOut className="size-4" />
                  </button>
                </div>
              </div>
            </aside>
            <main key={pathname} className="animate-enter min-w-0 flex-1 p-4 md:p-8">
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
