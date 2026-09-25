"use client";

import { useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";

/** Clipboard API when available (HTTPS, localhost); plain HTTP falls back to execCommand. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand("copy");
    } finally {
      area.remove();
    }
  }
}

/** `copy(text)` then `bubble` shows "Text copied!" for 1.5 s (place it in a `relative` parent). */
export function useCopy() {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const copy = async (text: string) => {
    if (!(await copyText(text))) return;
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  const bubble = (
    <span role="status" aria-live="polite" className="pointer-events-none absolute -top-9 left-1/2 z-20 -translate-x-1/2">
      {copied && (
        <span className="animate-enter block whitespace-nowrap rounded-md bg-foreground px-2 py-1 font-sans text-xs text-background shadow-md">
          {t("common.textCopied")}
        </span>
      )}
    </span>
  );
  return { copied, copy, bubble };
}
