import { readFileSync } from "node:fs";

import { test as base, type BrowserContext } from "@playwright/test";

export * from "@playwright/test";

const VERSION = JSON.parse(readFileSync("package.json", "utf8")).version as string;

/** The "what's new" pop-up already seen in this browser (it would cover every page). */
export async function seenWhatsNew(context: BrowserContext) {
  await context.addInitScript((v) => {
    try {
      localStorage.setItem("hivora.whatsNew", v);
    } catch {
      /* about:blank */
    }
  }, VERSION);
}

/** Every e2e test: the pop-up seen (whats-new.spec.ts opens a fresh context to see it). */
export const test = base.extend({
  context: async ({ context }, use) => {
    await seenWhatsNew(context);
    await use(context);
  },
});
