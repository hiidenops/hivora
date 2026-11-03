"use client";

import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState, type ComponentProps, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { readPref, writePref } from "@/lib/prefs";
import { cn } from "@/lib/utils";

export const Sheet = D.Root;

const MIN = 360;
const clamp = (w: number) => Math.round(Math.min(Math.max(w, MIN), window.innerWidth));

/** A panel sliding in from the right over the page (a dialog: Escape, focus kept inside).
 *  Its left edge drags to any width (arrows from the keyboard, double click: back to the
 *  default), remembered per ``widthKey`` in this browser. */
export function SheetContent({
  title,
  icon,
  className,
  children,
  closeLabel,
  resizeLabel,
  widthKey = "default",
  style,
  ...props
}: ComponentProps<typeof D.Content> & { title: ReactNode; icon?: ReactNode; closeLabel: string; resizeLabel: string; widthKey?: string }) {
  const key = `sheet.${widthKey}` as const;
  const [width, setWidth] = useState<number | null>(() => Number(readPref(key)) || null);
  const resize = (w: number | null) => {
    setWidth(w);
    writePref(key, w ? String(w) : "");
  };
  const drag = (e: PointerEvent<HTMLDivElement>) => {
    if (e.buttons !== 1 || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
    setWidth(clamp(window.innerWidth - e.clientX));
  };
  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowLeft" ? 40 : e.key === "ArrowRight" ? -40 : 0;
    if (!step) return;
    e.preventDefault();
    const panel = e.currentTarget.parentElement as HTMLElement;
    resize(clamp(panel.getBoundingClientRect().width + step));
  };
  return (
    <D.Portal>
      <D.Overlay className="animate-overlay fixed inset-0 z-40 bg-black/30" />
      <D.Content
        aria-describedby={undefined}
        className={cn(
          "animate-sheet fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-background shadow-2xl sm:max-w-3xl",
          className,
        )}
        style={width ? { ...style, width, maxWidth: "100vw" } : style}
        {...props}
      >
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={resizeLabel}
          tabIndex={0}
          title={resizeLabel}
          className="absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-0.5 after:-translate-x-1/2 after:bg-primary after:opacity-0 after:transition-opacity hover:after:opacity-100 focus-visible:after:opacity-100 sm:block"
          onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
          onPointerMove={drag}
          onPointerUp={() => width && resize(width)}
          onDoubleClick={() => resize(null)}
          onKeyDown={keys}
        />
        <div className="flex items-center justify-between gap-4 border-b bg-card px-5 py-4">
          <D.Title className="flex items-center gap-2 text-lg font-semibold">
            {icon}
            {title}
          </D.Title>
          <D.Close
            aria-label={closeLabel}
            className="grid size-9 place-items-center rounded-full text-muted-foreground transition-transform duration-300 ease-(--ease-spring) hover:rotate-90 hover:scale-110 hover:bg-muted hover:text-foreground active:scale-90"
          >
            <X className="size-5" />
          </D.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </D.Content>
    </D.Portal>
  );
}
