"use client";

import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Sheet = D.Root;

/** A panel sliding in from the right over the page (a dialog: Escape, focus kept inside). */
export function SheetContent({
  title,
  icon,
  className,
  children,
  closeLabel,
  ...props
}: ComponentProps<typeof D.Content> & { title: ReactNode; icon?: ReactNode; closeLabel: string }) {
  return (
    <D.Portal>
      <D.Overlay className="animate-overlay fixed inset-0 z-40 bg-black/30" />
      <D.Content
        aria-describedby={undefined}
        className={cn(
          "animate-sheet fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-background shadow-2xl sm:max-w-3xl",
          className,
        )}
        {...props}
      >
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
