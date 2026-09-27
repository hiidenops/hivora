"use client";

import { Slot } from "@radix-ui/react-slot";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

// A small menu (the Radix one cost ~19 KB gzip on the only page using it).
// Button with aria-expanded, role=menu/menuitem, Escape and outside click close it,
// the first item takes focus on open.
const Ctx = createContext<{ open: boolean; setOpen: (o: boolean) => void } | null>(null);
const useMenu = () => useContext(Ctx)!;

export function DropdownMenu({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <Ctx.Provider value={{ open, setOpen }}>
      <div ref={root} className="relative inline-block">
        {children}
      </div>
    </Ctx.Provider>
  );
}

export function DropdownMenuTrigger({ asChild, ...props }: ComponentProps<"button"> & { asChild?: boolean }) {
  const { open, setOpen } = useMenu();
  const Comp = asChild ? Slot : "button";
  return <Comp aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} {...props} />;
}

export function DropdownMenuContent({ className, ...props }: ComponentProps<"div">) {
  const { open } = useMenu();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) ref.current?.querySelector<HTMLElement>("[role=menuitem]:not(:disabled)")?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div
      ref={ref}
      role="menu"
      data-state="open"
      className={cn("animate-menu absolute right-0 top-full z-50 mt-1 min-w-44 rounded-md border bg-card p-1 shadow-md", className)}
      {...props}
    />
  );
}

export function DropdownMenuItem({
  className,
  onSelect,
  ...props
}: Omit<ComponentProps<"button">, "onSelect"> & { onSelect?: () => void }) {
  const { setOpen } = useMenu();
  return (
    <button
      type="button"
      role="menuitem"
      onClick={() => {
        setOpen(false);
        onSelect?.();
      }}
      className={cn(
        "flex w-full select-none items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm outline-none hover:bg-muted focus-visible:bg-muted disabled:opacity-50 [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-border" />;
}
