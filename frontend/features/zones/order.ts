// A zone's start order from the dependencies between its apps, as the server computes it
// (backend apps/start_order.py), to redraw the graph's columns at once while editing. The
// server checks again when saved.

/** `app` starts after `after`. */
export type Dep = { app: number; after: number };

/** The apps step by step (each step sorted), or the apps of a loop (no order then). */
export function order(apps: number[], deps: Dep[]): { steps: number[][] } | { loop: number[] } {
  const members = new Set(apps);
  const needs = new Map(apps.map((a) => [a, new Set<number>()]));
  for (const d of deps) if (members.has(d.app) && members.has(d.after)) needs.get(d.app)!.add(d.after);
  const placed = new Set<number>();
  const steps: number[][] = [];
  while (placed.size < members.size) {
    const step = apps.filter((a) => !placed.has(a) && [...needs.get(a)!].every((n) => placed.has(n))).sort((x, y) => x - y);
    if (!step.length) return { loop: loopOf(apps.filter((a) => !placed.has(a)), needs, placed) };
    steps.push(step);
    step.forEach((a) => placed.add(a));
  }
  return { steps };
}

/** One loop among apps that all wait: followed from the smallest until an app comes back. */
function loopOf(waiting: number[], needs: Map<number, Set<number>>, placed: Set<number>): number[] {
  const seen: number[] = [];
  let app = Math.min(...waiting);
  while (!seen.includes(app)) {
    seen.push(app);
    app = Math.min(...[...needs.get(app)!].filter((n) => !placed.has(n)));
  }
  return seen.slice(seen.indexOf(app));
}
