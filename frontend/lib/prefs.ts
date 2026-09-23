/** Per-browser preferences (language, theme, advanced mode). Storage may be unavailable. */
export type PrefKey = "lang" | "theme" | "advanced";

export function readPref(key: PrefKey): string | null {
  try {
    return localStorage.getItem(`hivora.${key}`);
  } catch {
    return null;
  }
}

export function writePref(key: PrefKey, value: string) {
  try {
    localStorage.setItem(`hivora.${key}`, value);
  } catch {
    /* private mode: preference lasts for this page only */
  }
}
