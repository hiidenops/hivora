import { networkInterfaces } from "node:os";

// Browse through the LAN IP, like real users: plain HTTP there is NOT a secure
// context (unlike 127.0.0.1), so HTTPS-only browser APIs break the tests too.
export const HOST =
  Object.values(networkInterfaces())
    .flat()
    .find((i) => i && i.family === "IPv4" && !i.internal)?.address ?? "127.0.0.1";

export const PORT = 18500;
// A second server, as a panel reachable from the Internet (HIVORA_ACCESS=public).
export const PUBLIC_PORT = 18501;
// A third one, reached through the admin VPN (HIVORA_ACCESS=vpn): admin-vpn.spec.ts.
export const VPN_PORT = 18502;
