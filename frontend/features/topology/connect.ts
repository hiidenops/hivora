import type { Change } from "./changes";
import type { GNode, Port } from "./layout";

/** What linking two nodes means: prepared changes, a message (nothing would happen), or a
 *  drawn link to save (with a declared item). */
export type LinkOutcome =
  | { kind: "changes"; changes: Change[] }
  | { kind: "noEffect" }
  | { kind: "nothingClosed"; app: string }
  | { kind: "vpnZoneOnly"; app: string }
  | { kind: "vpnZoneNoPublish"; app: string }
  | { kind: "declared" };

/** The rules of a link drawn between `a` and `b` (pure: the caller applies the result). */
export function connectNodes(a: GNode | undefined, b: GNode | undefined): LinkOutcome {
  const vpn = a?.vpn ? a : b?.vpn ? b : null;
  const other = vpn === a ? b : a;
  // From a VPN to a zone: a real change (the VPN joins its network, its apps publish nothing).
  // Between the Internet and an app: open again what was closed (the template's own exposure).
  const inet = a?.type === "internet" ? b : b?.type === "internet" ? a : null;
  if (inet) {
    if (inet.type !== "app") return { kind: "noEffect" };
    if (inet.behind_vpn) return { kind: "vpnZoneNoPublish", app: String(inet.label) };
    const closed = (inet.ports as Port[]).filter((p) => p.override === "none" && p.default && p.default !== "internal");
    if (!closed.length) return { kind: "nothingClosed", app: String(inet.label) };
    return {
      kind: "changes",
      changes: closed.map((p) => ({ kind: "expose", appId: Number(inet.id), app: String(inet.label), service: p.service, port: `${p.container}/${p.protocol}`, exposure: "default" })),
    };
  }
  if (vpn && other?.type === "app") return { kind: "vpnZoneOnly", app: String(other.label) };
  if (vpn && other?.type === "zone" && other.slug) {
    return { kind: "changes", changes: [{ kind: "reach", vpnId: Number(vpn.id), vpn: String(vpn.label), target: String(other.slug), targetLabel: String(other.label), on: true }] };
  }
  // A drawn link only makes sense with a declared item (router, firewall, note...).
  if (a?.type !== "declared" && b?.type !== "declared") return { kind: "noEffect" };
  return { kind: "declared" };
}
