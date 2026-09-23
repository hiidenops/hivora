"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/** Template icon served by Hivora, or the first letter when there is none. */
export function AppIcon({ src, name, className }: { src?: string | null; name: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={cn(
        "grid size-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-muted font-semibold uppercase",
        className,
      )}
    >
      {src && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- static export, icon served by the API
        <img src={src} alt="" className="size-full object-cover" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        name.slice(0, 1)
      )}
    </span>
  );
}
