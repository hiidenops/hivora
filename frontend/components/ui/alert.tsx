import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const tones = {
  info: "border-info/40 bg-info/10",
  warn: "border-warn/50 bg-warn/10",
  danger: "border-danger/40 bg-danger/10",
};

export function Alert({ tone = "info", className, ...props }: ComponentProps<"div"> & { tone?: keyof typeof tones }) {
  return <div role="alert" className={cn("rounded-md border px-3 py-2 text-sm", tones[tone], className)} {...props} />;
}
