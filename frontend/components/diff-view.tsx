import { cn } from "@/lib/utils";

/** Unified diff with added/removed lines coloured (text stays readable, the sign carries meaning). */
export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md border bg-muted p-3 font-mono text-xs leading-relaxed">
      {diff.split("\n").map((line, i) => (
        <div
          key={i}
          className={cn(
            line.startsWith("+") && !line.startsWith("+++") && "bg-ok/15",
            line.startsWith("-") && !line.startsWith("---") && "bg-danger/15",
            line.startsWith("@@") && "text-muted-foreground",
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}
