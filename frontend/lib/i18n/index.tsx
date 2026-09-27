"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { readPref, writePref } from "@/lib/prefs";

import { fr, type MessageKey } from "./fr";

export type Lang = "fr" | "en";
export type { MessageKey };
export const LANGS: Lang[] = ["fr", "en"];
type Dict = Record<MessageKey, string>;
// French ships with every page; English is fetched only when chosen (bundle budget).
const loaders: Record<Lang, () => Promise<Dict>> = {
  fr: async () => fr,
  en: async () => (await import("./en")).en,
};

type Vars = Record<string, string | number>;
/** Text from templates: plain, or one string per language. */
export type Localized = string | Partial<Record<Lang, string>>;

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, vars?: Vars) => string;
  l: (text: Localized | null | undefined) => string;
  errorMessage: (error: unknown) => string;
}

const I18nContext = createContext<I18n | null>(null);

function interpolate(text: string, vars?: Vars) {
  return vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : text;
}

function detect(): Lang {
  const saved = readPref("lang");
  if (saved === "fr" || saved === "en") return saved;
  return typeof navigator !== "undefined" && navigator.language.startsWith("fr") ? "fr" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("fr");
  const [dict, setDict] = useState<Dict>(fr);
  const switchTo = useCallback((next: Lang) => {
    void loaders[next]().then((d) => {
      setDict(d);
      setLangState(next);
    });
  }, []);
  useEffect(() => switchTo(detect()), [switchTo]);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback(
    (next: Lang) => {
      writePref("lang", next);
      switchTo(next);
    },
    [switchTo],
  );

  const value = useMemo<I18n>(() => {
    const t = (key: MessageKey, vars?: Vars) => interpolate(dict[key] ?? key, vars);
    const l = (text: Localized | null | undefined) =>
      !text ? "" : typeof text === "string" ? text : (text[lang] ?? text.en ?? Object.values(text)[0] ?? "");
    const errorMessage = (error: unknown) => {
      if (error instanceof ApiError) {
        const key = `error.${error.code}` as MessageKey;
        if (key in dict) {
          return t(key, { message: error.message, seconds: String(error.details.retry_after ?? "") });
        }
        return t("error.generic", { message: error.message });
      }
      return t("error.generic", { message: error instanceof Error ? error.message : String(error) });
    };
    return { lang, setLang, t, l, errorMessage };
  }, [lang, dict, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
