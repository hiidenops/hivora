"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** The live connections moved to the firewall's home: older links land there. */
export default function FirewallConnectionsPage() {
  const router = useRouter();
  useEffect(() => router.replace("/firewall/"), [router]);
  return null;
}
