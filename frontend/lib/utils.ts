import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** The web address to open from here: through the VPN when that is the only way; the public
 *  one when the panel itself is reached on that host; otherwise the local network's. */
export function webAddress(web: Record<string, string>): string | undefined {
  if (web.web_vpn && !web.web && !web.web_lan) return web.web_vpn;
  const here = typeof window === "undefined" ? "" : window.location.hostname;
  if (web.web && here && new URL(web.web).hostname === here) return web.web;
  return web.web_lan ?? web.web ?? web.web_vpn;
}
