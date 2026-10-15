/** Where the running version's source code is (AGPL-3.0, section 13). A release version
 * links its tag; anything else, the repository itself. */
export function sourceLink(base: string, version: string): string {
  const root = base.replace(/\/+$/, "");
  return /^\d+\.\d+\.\d+(-rc\.\d+)?$/.test(version) ? `${root}/tree/v${version}` : root;
}

/** The page was built for another server version (an update happened): reload it. */
export function staleFrontend(built: string | undefined, server: string | undefined): boolean {
  return !!built && !!server && built !== server;
}
