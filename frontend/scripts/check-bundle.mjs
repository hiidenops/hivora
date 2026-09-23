// Fails when a page's initial JavaScript exceeds the budget (CLAUDE.md: < 250 KB gzip).
// Counts every <script src> of each exported HTML page, gzip-compressed.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { gzipSync } from "node:zlib";

const OUT = new URL("../out/", import.meta.url).pathname;
const BUDGET = 250 * 1024;

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "_next" ? [] : htmlFiles(path);
    return name.endsWith(".html") ? [path] : [];
  });
}

const cache = new Map();
const gz = (src) => {
  if (!cache.has(src)) cache.set(src, gzipSync(readFileSync(join(OUT, src))).length);
  return cache.get(src);
};

let failed = false;
for (const file of htmlFiles(OUT).sort()) {
  const html = readFileSync(file, "utf8");
  const scripts = [...new Set([...html.matchAll(/<script[^>]+src="\/?([^"]+)"/g)].map((m) => m[1]))];
  const total = scripts.reduce((sum, s) => sum + gz(s), 0);
  const ok = total <= BUDGET;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "FAIL"} ${(total / 1024).toFixed(1).padStart(6)} KB  /${relative(OUT, file)}`);
}
console.log(`budget: ${BUDGET / 1024} KB gzip per page`);
process.exit(failed ? 1 : 0);
