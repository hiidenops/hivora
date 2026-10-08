"use client";

import { FileArchive, Upload } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";

import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** A file picker as a centered dashed frame: click it or drop a file on it. The real input
 *  stays (visually hidden): keyboard, screen readers and tests use it. `file` null clears it. */
export function FileDrop({ label, accept, file, onFile, title, hint, disabled = false }: {
  label: string; // the input's accessible name
  accept?: string;
  file: File | null;
  onFile: (file: File | null) => void;
  title?: string; // default: "Choose a .zip archive"
  hint?: string; // under the title while no file is chosen; default: "or drop it here"
  disabled?: boolean;
}) {
  const { t, lang } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!file && input.current) input.current.value = ""; // sent or cleared: pick again
  }, [file]);

  const size = (bytes: number) => {
    const [n, unit] = bytes >= 1024 ** 3 ? [bytes / 1024 ** 3, "gigabyte"] : bytes >= 1024 ** 2 ? [bytes / 1024 ** 2, "megabyte"] : [bytes / 1024, "kilobyte"];
    return new Intl.NumberFormat(lang, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 1 }).format(n);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (!disabled && dropped) onFile(dropped);
  };

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        "grid w-full cursor-pointer place-items-center gap-1 rounded-lg border-2 border-dashed border-input px-4 py-6 text-center transition-colors duration-200",
        "hover:border-primary/60 hover:bg-muted/40 focus-within:border-ring focus-within:bg-muted/40",
        over && "border-primary bg-primary/10",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        aria-label={label}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      {file ? <FileArchive aria-hidden className="size-7 text-primary" /> : <Upload aria-hidden className="size-7 text-muted-foreground" />}
      <span className="max-w-full truncate text-sm font-medium">{file ? file.name : (title ?? t("drop.chooseZip"))}</span>
      <span className="text-xs text-muted-foreground">{file ? `${size(file.size)} · ${t("drop.another")}` : (hint ?? t("drop.orDrop"))}</span>
    </label>
  );
}
