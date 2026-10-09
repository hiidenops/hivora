"use client";

import { LiveConnections } from "@/features/firewall/connections";
import { useHost } from "@/features/firewall/host";

export default function FirewallConnectionsPage() {
  const { act, state } = useHost();
  return <LiveConnections act={act} jails={state.data?.fail2ban_running ? state.data.jails : []} />;
}
