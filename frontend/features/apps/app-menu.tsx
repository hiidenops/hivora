"use client";

import {
  Archive,
  CalendarClock,
  FileArchive,
  Menu,
  Network,
  Pencil,
  ScrollText,
  SlidersHorizontal,
  SquareTerminal,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useSession } from "@/components/app-shell";
import { Unfolded } from "@/components/collapsible-card";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { ConsolePanel } from "@/features/console/console-panel";
import { ZoneSelect } from "@/features/zones/zone-select";
import type { AppDetail } from "@/lib/api/client";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { RemoveDialog } from "./remove-dialog";

// Loaded when their panel opens: the app's page stays light.
const BackupsCard = dynamic(() => import("@/features/backups/backups-card").then((m) => m.BackupsCard));
const TasksCard = dynamic(() => import("@/features/tasks/tasks-card").then((m) => m.TasksCard));
const LogsCard = dynamic(() => import("@/features/logs/logs-card").then((m) => m.LogsCard));
const PythonCodeCard = dynamic(() => import("@/features/apps/python-code-card").then((m) => m.PythonCodeCard));
const AdvancedCards = dynamic(() => import("@/features/apps/advanced-cards").then((m) => m.AdvancedCards));

type Section = "zone" | "backups" | "tasks" | "logs" | "console" | "code" | "advanced";
type Entry = { key: Section | "edit" | "remove"; icon: LucideIcon; label: MessageKey };

/** The app's secondary actions behind one round button (top right of its page): simple
 *  buttons, each opening its section in a side panel (or the settings page, or the removal). */
export function AppMenu({ app, running, onJob, onRemoving }: {
  app: AppDetail;
  running: boolean;
  onJob: (jobId: number) => void;
  onRemoving: (jobId: number) => void;
}) {
  const { t } = useI18n();
  const { can, advanced } = useSession();
  const router = useRouter();
  const [section, setSection] = useState<Section | null>(null);
  const [removing, setRemoving] = useState(false);
  const operator = can("operator");

  const entries: Entry[] = [
    ...(operator && app.template ? [{ key: "zone", icon: Network, label: "zones.move" } as const] : []),
    ...(operator && app.template ? [{ key: "edit", icon: Pencil, label: "edit.button" } as const] : []),
    ...(operator ? [{ key: "backups", icon: Archive, label: "backups.title" } as const] : []),
    ...(operator ? [{ key: "tasks", icon: CalendarClock, label: "tasks.title" } as const] : []),
    ...(operator ? [{ key: "logs", icon: ScrollText, label: "logs.title" } as const] : []),
    ...(operator ? [{ key: "console", icon: SquareTerminal, label: "console.title" } as const] : []),
    ...(operator && app.python ? [{ key: "code", icon: FileArchive, label: "py.code" } as const] : []),
    ...(advanced ? [{ key: "advanced", icon: SlidersHorizontal, label: "app.menuAdvanced" } as const] : []),
  ];
  if (entries.length === 0 && !operator) return null;

  const body: Record<Section, ReactNode> = {
    zone: (
      <div className="grid max-w-md gap-3">
        <p className="text-sm text-muted-foreground">{t("zones.intro")}</p>
        <ZoneSelect appId={app.id} zoneId={app.zone_id} onJob={onJob} />
      </div>
    ),
    backups: <BackupsCard appId={app.id} onJob={onJob} />,
    tasks: <TasksCard appId={app.id} />,
    logs: <LogsCard appId={app.id} />,
    console: <ConsolePanel app={app} running={running} />,
    code: <PythonCodeCard appId={app.id} onJob={onJob} />,
    advanced: (
      <div className="grid gap-4">
        <AdvancedCards app={app} onJob={onJob} />
      </div>
    ),
  };
  const current = entries.find((e) => e.key === section);
  const item = "gap-3 rounded-lg px-2.5 py-2 text-sm transition-[background-color,translate] duration-200 ease-(--ease-spring) hover:translate-x-0.5 [&_svg]:size-4";
  const iconBox = (Icon: LucideIcon, danger = false) => (
    <span className={cn("grid size-8 shrink-0 place-items-center rounded-full", danger ? "bg-danger/10 text-danger" : "bg-muted text-foreground")}>
      <Icon />
    </span>
  );

  return (
    <>
      <DropdownMenu>
        <MenuButton label={t("app.menu")} />
        <DropdownMenuContent className="animate-burger stagger mt-2 grid w-64 gap-0.5 rounded-xl p-2 shadow-xl">
          {entries.map((e) => (
            <DropdownMenuItem
              key={e.key}
              className={item}
              onSelect={() => (e.key === "edit" ? router.push(`/edit/?id=${app.id}`) : setSection(e.key as Section))}
            >
              {iconBox(e.icon)} {t(e.label)}
            </DropdownMenuItem>
          ))}
          {operator && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem className={cn(item, "text-danger")} onSelect={() => setRemoving(true)}>
                {iconBox(Trash2, true)} {t("action.remove")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <Sheet open={section !== null} onOpenChange={(o) => !o && setSection(null)}>
        {current && section && (
          <SheetContent title={t(current.label)} icon={<current.icon className="size-5" />} closeLabel={t("common.close")}>
            <Unfolded.Provider value>{body[section]}</Unfolded.Provider>
          </SheetContent>
        )}
      </Sheet>
      {operator && (
        <RemoveDialog id={app.id} name={app.name} open={removing} onOpenChange={setRemoving} onJob={onRemoving} />
      )}
    </>
  );
}

/** The round menu button: its three bars turn into a cross while the menu is open. */
function MenuButton({ label }: { label: string }) {
  return (
    <DropdownMenuTrigger asChild>
      <Button
        variant="outline"
        size="icon"
        aria-label={label}
        title={label}
        className="group relative size-10 rounded-full transition-transform duration-300 ease-(--ease-spring) hover:scale-110 active:scale-95"
      >
        <Menu className="absolute size-5 transition-[rotate,scale,opacity] duration-300 ease-(--ease-spring) group-aria-expanded:rotate-90 group-aria-expanded:scale-50 group-aria-expanded:opacity-0" />
        <X className="absolute size-5 -rotate-90 scale-50 opacity-0 transition-[rotate,scale,opacity] duration-300 ease-(--ease-spring) group-aria-expanded:rotate-0 group-aria-expanded:scale-100 group-aria-expanded:opacity-100" />
      </Button>
    </DropdownMenuTrigger>
  );
}
