"use client";

import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  title,
  description,
  className,
  children,
  closeLabel,
  ...props
}: ComponentProps<typeof D.Content> & { title: ReactNode; description?: ReactNode; closeLabel: string }) {
  return (
    <D.Portal>
      <D.Overlay className="animate-overlay fixed inset-0 z-40 bg-black/40" />
      <D.Content
        className={cn(
          "animate-dialog fixed left-1/2 top-1/2 z-50 grid max-h-[90vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border bg-card p-6 shadow-lg",
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="grid gap-1">
            <D.Title className="text-lg font-semibold">{title}</D.Title>
            {description && <D.Description className="text-sm text-muted-foreground">{description}</D.Description>}
          </div>
          <D.Close className="rounded-sm opacity-70 hover:opacity-100" aria-label={closeLabel}>
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  );
}
