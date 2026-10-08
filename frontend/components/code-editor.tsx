"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

/** The languages the code editor colors ("text": none). */
export type CodeLanguage = "html" | "css" | "js" | "yaml" | "properties" | "text";

export type CodeEditorProps = {
  value: string;
  onChange: (value: string) => void;
  language: CodeLanguage;
  label?: string; // its accessible name, or:
  labelledBy?: string; // the id of its <label>
  id?: string;
  describedBy?: string;
  invalid?: boolean;
  placeholder?: string;
  readOnly?: boolean;
  onSave?: () => void; // Ctrl/Cmd+S
  height?: string; // CSS length; resizable from there
};

/** The language of a file, by its extension. */
export function languageOfPath(path: string): CodeLanguage {
  const ext = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
  const known: Record<string, CodeLanguage> = {
    html: "html", htm: "html", css: "css", js: "js", mjs: "js", yaml: "yaml", yml: "yaml", properties: "properties",
  };
  return known[ext] ?? "text";
}

/** CodeMirror, loaded only when an editor is shown (out of the pages' first bundle). */
export const CodeEditor = dynamic<CodeEditorProps>(() => import("./code-editor-impl").then((m) => m.CodeEditorImpl), {
  ssr: false,
  loading: () => <Skeleton className="h-40" />,
});
