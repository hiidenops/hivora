"use client";

import { ChevronRight, FileCode, Folder, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Item = { path: string; size: number };
type Dir = { name: string; path: string; dirs: Dir[]; files: Item[] };

/** The folders the paths imply ("css/site.css" -> folder "css"), folders first, each by name. */
export function buildTree(files: Item[]): Dir {
  const root: Dir = { name: "", path: "", dirs: [], files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let dir = root;
    for (const name of parts.slice(0, -1)) {
      const path = dir.path ? `${dir.path}/${name}` : name;
      let next = dir.dirs.find((d) => d.name === name);
      if (!next) dir.dirs.push((next = { name, path, dirs: [], files: [] }));
      dir = next;
    }
    dir.files.push(file);
  }
  const sort = (dir: Dir) => {
    dir.dirs.sort((a, b) => a.name.localeCompare(b.name));
    dir.files.sort((a, b) => a.path.localeCompare(b.path));
    dir.dirs.forEach(sort);
  };
  sort(root);
  return root;
}

const indent = (depth: number) => ({ paddingLeft: `${0.5 + depth * 1.1}rem` });

/** The site's files as folders and files; folders open by default, the open file's always. */
export function FileTree({ files, current, onOpen, label }: { files: Item[]; current: string | null; onOpen: (path: string) => void; label: string }) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  // The folders of the open file stay open (a new file may be in a folded one).
  useEffect(() => {
    if (!current) return;
    setClosed((prev) => {
      const next = new Set([...prev].filter((p) => !current.startsWith(`${p}/`)));
      return next.size === prev.size ? prev : next;
    });
  }, [current]);
  const toggle = (path: string) =>
    setClosed((prev) => {
      const next = new Set(prev);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  return (
    <ul className="grid gap-0.5" aria-label={label}>
      <Entries dir={buildTree(files)} depth={0} closed={closed} toggle={toggle} current={current} onOpen={onOpen} />
    </ul>
  );
}

function Entries({ dir, depth, closed, toggle, current, onOpen }: {
  dir: Dir; depth: number; closed: Set<string>; toggle: (path: string) => void; current: string | null; onOpen: (path: string) => void;
}) {
  const { t, lang } = useI18n();
  return (
    <>
      {dir.dirs.map((d) => {
        const open = !closed.has(d.path);
        return (
          <li key={d.path}>
            <button
              type="button"
              aria-expanded={open}
              title={t(open ? "sites.folderCollapse" : "sites.folderExpand", { name: d.path })}
              onClick={() => toggle(d.path)}
              style={indent(depth)}
              className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left hover:bg-muted"
            >
              <ChevronRight aria-hidden className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform duration-300 ease-(--ease-out)", open && "rotate-90")} />
              {open ? <FolderOpen aria-hidden className="size-4 shrink-0 text-primary" /> : <Folder aria-hidden className="size-4 shrink-0 text-primary" />}
              <span className="truncate font-mono text-sm">{d.name}</span>
            </button>
            {/* grid-rows 0fr <-> 1fr animates the height without measuring it */}
            <div
              className={cn("grid transition-[grid-template-rows] duration-[420ms] ease-(--ease-out)", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}
              inert={!open}
            >
              {/* invisible once folded (visibility switches at the end of the fade): hidden for real */}
              <ul className={cn("grid gap-0.5 overflow-hidden transition-[opacity,translate,visibility] duration-[420ms] ease-(--ease-out)", open ? "visible translate-y-0 opacity-100" : "invisible -translate-y-1 opacity-0")}>
                <Entries dir={d} depth={depth + 1} closed={closed} toggle={toggle} current={current} onOpen={onOpen} />
              </ul>
            </div>
          </li>
        );
      })}
      {dir.files.map((f) => (
        <li key={f.path}>
          <button
            type="button"
            aria-current={f.path === current || undefined}
            title={f.path}
            onClick={() => onOpen(f.path)}
            style={indent(depth)}
            className={cn("flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left hover:bg-muted", f.path === current && "bg-muted")}
          >
            <span aria-hidden className="size-3.5 shrink-0" />
            <FileCode aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate font-mono text-sm">{f.path.split("/").pop()}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{t("sites.size", { size: f.size.toLocaleString(lang) })}</span>
          </button>
        </li>
      ))}
    </>
  );
}
