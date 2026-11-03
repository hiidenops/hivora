import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// ponytail: the CHANGELOG's subset only (headings, lists, paragraphs, **bold**, `code`,
// [links](https://…)); a library if the notes ever need tables or nested lists.
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) return <code key={i} className="rounded bg-muted px-1 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{inline(part.slice(2, -2))}</strong>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      return /^https?:\/\//.test(link[2]) ? (
        <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
          {inline(link[1])}
        </a>
      ) : (
        inline(link[1])
      );
    }
    return part;
  });
}

type Block = { kind: "h"; level: number; text: string } | { kind: "ul"; items: string[] } | { kind: "p"; text: string };

function blocks(source: string): Block[] {
  const out: Block[] = [];
  for (const line of source.split("\n")) {
    const last = out[out.length - 1];
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    if (!line.trim()) out.push({ kind: "p", text: "" });
    else if (heading) out.push({ kind: "h", level: heading[1].length, text: heading[2] });
    else if (item) {
      if (last?.kind === "ul") last.items.push(item[1]);
      else out.push({ kind: "ul", items: [item[1]] });
    } else if (last?.kind === "ul" && /^\s/.test(line)) last.items[last.items.length - 1] += ` ${line.trim()}`;
    else if (last?.kind === "p" && last.text) last.text += ` ${line.trim()}`;
    else out.push({ kind: "p", text: line.trim() });
  }
  return out.filter((b) => b.kind !== "p" || b.text);
}

/** Release notes written in Markdown, as React elements (no HTML from the text). */
export function Markdown({ source, className }: { source: string; className?: string }) {
  return (
    <div className={cn("grid gap-2 text-sm leading-relaxed", className)}>
      {blocks(source).map((b, i) =>
        b.kind === "h" ? (
          <p key={i} className={cn("font-semibold", b.level <= 2 ? "mt-2 text-base" : "mt-1")}>
            {inline(b.text)}
          </p>
        ) : b.kind === "ul" ? (
          <ul key={i} className="grid list-disc gap-1.5 pl-5 marker:text-primary">
            {b.items.map((it, j) => (
              <li key={j}>{inline(it)}</li>
            ))}
          </ul>
        ) : (
          <p key={i}>{inline(b.text)}</p>
        ),
      )}
    </div>
  );
}
