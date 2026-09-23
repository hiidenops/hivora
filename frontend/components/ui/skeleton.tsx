import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div aria-hidden className={cn("skeleton", className)} {...props} />;
}

/** Placeholder grid shown while tiles load (announced once to screen readers). */
export function TileSkeletons({ count = 6, label, className }: { count?: number; label: string; className?: string }) {
  return (
    <div role="status" aria-label={label} className={cn("grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3", className)}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          <div className="flex items-center gap-3">
            <Skeleton className="size-10" />
            <div className="grid flex-1 gap-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
          <Skeleton className="h-4 w-1/4" />
        </div>
      ))}
    </div>
  );
}
