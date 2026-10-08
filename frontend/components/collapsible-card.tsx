"use client";

import { ChevronDown } from "lucide-react";
import { createContext, useContext, useEffect, useId, useState, type ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { readPref, writePref } from "@/lib/prefs";
import { cn } from "@/lib/utils";

/** Inside it (a side panel shows one section), a CollapsibleCard is its body only, always
 *  open: the panel already has the title and the frame. */
export const Unfolded = createContext(false);

/** Card whose body folds away (folded unless `defaultOpen`); the choice is remembered per `storageKey`. */
export function CollapsibleCard({
  title,
  aside,
  storageKey,
  className,
  onToggle,
  defaultOpen = false,
  children,
}: {
  title: ReactNode;
  aside?: ReactNode; // stays visible when folded (e.g. a counter)
  storageKey: string;
  className?: string;
  onToggle?: (open: boolean) => void; // e.g. stream only while open
  defaultOpen?: boolean; // until the user folds or unfolds it once
  children: ReactNode;
}) {
  const unfolded = useContext(Unfolded);
  const [folded, setOpen] = useState(false);
  const open = unfolded || folded;
  const bodyId = useId();
  useEffect(() => {
    const saved = readPref(`fold.${storageKey}`);
    setOpen(saved === null ? defaultOpen : saved === "1");
  }, [storageKey, defaultOpen]);
  useEffect(() => onToggle?.(open), [open, onToggle]);
  const toggle = () => {
    writePref(`fold.${storageKey}`, open ? "0" : "1");
    setOpen(!open);
  };
  if (unfolded) {
    return (
      <div className="flex h-full min-h-0 flex-col gap-4">
        {aside && <div className="self-end">{aside}</div>}
        {children}
      </div>
    );
  }
  return (
    <Card className={className}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center justify-between gap-3 rounded-t-xl p-5 text-left transition-colors duration-200 hover:bg-muted/50"
      >
        <span className="flex items-center gap-2 font-semibold leading-tight">{title}</span>
        <span className="flex items-center gap-3">
          {aside}
          <ChevronDown className={cn("size-4 transition-transform duration-300 ease-(--ease-out)", !open && "-rotate-90")} aria-hidden />
        </span>
      </button>
      {/* grid-rows 0fr <-> 1fr animates the height without measuring it */}
      <div
        id={bodyId}
        className={cn("grid transition-[grid-template-rows] duration-[420ms] ease-(--ease-out)", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}
      >
        <div
          className={cn(
            "overflow-hidden transition-[opacity,translate] duration-[420ms] ease-(--ease-out)",
            open ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0",
          )}
        >
          <CardContent>{children}</CardContent>
        </div>
      </div>
    </Card>
  );
}
