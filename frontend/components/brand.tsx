import { cn } from "@/lib/utils";

/** "Hivora / Panel" wordmark, centred, with a short honey rule between the two words. */
export function Brand({ className, large = false }: { className?: string; large?: boolean }) {
  return (
    <span className={cn("grid justify-items-center gap-1 text-center", className)}>
      <span className={cn("font-semibold leading-none tracking-tight", large ? "text-3xl" : "text-xl")}>Hivora</span>
      <span aria-hidden className="h-0.5 w-6 rounded-full bg-primary" />
      <span className={cn("leading-none text-muted-foreground", large ? "text-sm" : "text-xs")}>Panel</span>
    </span>
  );
}
