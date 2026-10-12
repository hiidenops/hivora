"use client";

import { Slot } from "@radix-ui/react-slot";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ComponentProps,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

// A small menu (the Radix one cost ~19 KB gzip on the only page using it).
// Button with aria-expanded, role=menu/menuitem, Escape and outside click close it,
// the first item takes focus on open. Open, it is drawn over the page (a portal, fixed
// under its button, above it when there is no room below): a scrolling frame around the
// button (a table's) neither cuts it nor grows a scrollbar. Scrolling or resizing moves it
// with its button.
type Menu = {
  open: boolean;
  setOpen: (o: boolean) => void;
  root: RefObject<HTMLDivElement | null>;
  content: RefObject<HTMLDivElement | null>;
};
const Ctx = createContext<Menu | null>(null);
const useMenu = () => useContext(Ctx)!;

export function DropdownMenu({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const inside = (target: EventTarget | null) =>
      !!target && (root.current?.contains(target as Node) || content.current?.contains(target as Node));
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !inside(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <Ctx.Provider value={{ open, setOpen, root, content }}>
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

export function DropdownMenuContent({ className, style, ...props }: ComponentProps<"div">) {
  const { open, root, content } = useMenu();
  const [place, setPlace] = useState<CSSProperties | null>(null);
  // Under the button, right edges aligned; above it when the menu would leave the screen.
  // Placed again when the page scrolls or resizes: it stays with its button.
  useLayoutEffect(() => {
    if (!open) return setPlace(null);
    const measure = () => {
      if (!root.current) return;
      const button = root.current.getBoundingClientRect();
      const right = window.innerWidth - button.right;
      const height = content.current?.offsetHeight ?? 0; // drawn hidden first, to be measured
      const below = button.bottom + 4 + height <= window.innerHeight - 8;
      const above = button.top - 4 - height >= 8;
      setPlace(below || !above ? { top: button.bottom, right } : { bottom: window.innerHeight - button.top, right, marginTop: 0, marginBottom: 4 });
    };
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, root, content]);
  useEffect(() => {
    // Once placed (visible): a hidden element takes no focus.
    if (open && place) content.current?.querySelector<HTMLElement>("[role=menuitem]:not(:disabled)")?.focus();
  }, [open, place, content]);
  if (!open) return null;
  return createPortal(
    <div
      ref={content}
      role="menu"
      data-state="open"
      style={{ ...place, visibility: place ? undefined : "hidden", ...style }}
      className={cn("animate-menu fixed z-50 mt-1 min-w-44 rounded-md border bg-card p-1 shadow-md", className)}
      {...props}
    />,
    document.body,
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
