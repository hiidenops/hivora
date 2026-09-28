import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const field =
  "field w-full rounded-md border border-input px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring disabled:opacity-50 aria-invalid:border-danger";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(field, "h-9", className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cn(field, "h-9 pr-8", className)} {...props} />;
}

export function Label({ className, ...props }: ComponentProps<"label">) {
  return <label className={cn("text-sm font-medium", className)} {...props} />;
}

/** iOS-style switch on a native checkbox: forms, labels and keyboard keep working. */
export function Switch({ className, ...props }: Omit<ComponentProps<"input">, "type" | "role">) {
  return (
    <span className={cn("relative inline-flex h-[26px] w-[44px] shrink-0", className)}>
      <input type="checkbox" role="switch" className="peer absolute inset-0 z-10 m-0 size-full cursor-pointer appearance-none opacity-0" {...props} />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-full bg-input shadow-[inset_0_1px_3px_var(--shadow-strong)] transition-colors duration-300 ease-(--ease-out) peer-checked:bg-primary peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring peer-disabled:opacity-50"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute left-[2px] top-[2px] size-[22px] rounded-full bg-white shadow-[0_3px_8px_rgba(0,0,0,0.15),0_3px_1px_rgba(0,0,0,0.06)] transition-transform duration-[380ms] ease-(--ease-spring) peer-checked:translate-x-[18px] peer-active:scale-x-110"
      />
    </span>
  );
}
