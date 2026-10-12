"use client";

import { useBlocked } from "@/features/firewall/blocked";
import { LiveConnections } from "@/features/firewall/connections";
import { useHost } from "@/features/firewall/host";

export default function FirewallConnectionsPage() {
  const { act } = useHost();
  const { data } = useBlocked();
  return <LiveConnections act={act} blocked={data?.map((b) => b.address)} />;
}
