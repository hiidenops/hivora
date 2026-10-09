import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

// One look for every table of the panel: a rounded frame (scrolling sideways inside it on
// a narrow screen), a tinted header in small capitals, airy rows lit on hover.

export function Table({ className, ...props }: ComponentProps<"table">) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className={cn("w-full border-collapse text-left text-sm", className)} {...props} />
    </div>
  );
}

export function THead({ className, ...props }: ComponentProps<"thead">) {
  return <thead className={cn("border-b bg-muted/60 text-[11px] uppercase tracking-wide text-muted-foreground", className)} {...props} />;
}

export function TBody({ className, ...props }: ComponentProps<"tbody">) {
  return <tbody className={cn("divide-y", className)} {...props} />;
}

export function Tr({ className, ...props }: ComponentProps<"tr">) {
  return <tr className={cn("transition-colors duration-150 hover:bg-muted/40", className)} {...props} />;
}

/** `numeric`: right-aligned (counts, sizes). */
export function Th({ className, numeric, ...props }: ComponentProps<"th"> & { numeric?: boolean }) {
  return <th scope="col" className={cn("whitespace-nowrap px-3 py-2 font-medium", numeric && "text-right", className)} {...props} />;
}

/** `numeric`: right-aligned, fixed-width digits; `mono`: addresses, ports, commands. */
export function Td({ className, numeric, mono, ...props }: ComponentProps<"td"> & { numeric?: boolean; mono?: boolean }) {
  return <td className={cn("px-3 py-2 align-middle", numeric && "text-right tabular-nums", mono && "font-mono text-xs", className)} {...props} />;
}

/** The message of an empty table, inside it. */
export function TEmpty({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-6 text-center text-sm text-muted-foreground">
        {children}
      </td>
    </tr>
  );
}
