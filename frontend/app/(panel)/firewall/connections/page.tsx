"use client";

import { LiveConnections } from "@/features/firewall/connections";
import { useHost } from "@/features/firewall/host";

export default function FirewallConnectionsPage() {
  const { act } = useHost();
  return <LiveConnections act={act} />;
}
