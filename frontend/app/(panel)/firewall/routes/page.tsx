"use client";

import { Routes } from "@/features/firewall/routes";
import { StaticRoutes } from "@/features/firewall/static-routes";

export default function FirewallRoutesPage() {
  return (
    <>
      <StaticRoutes />
      <Routes />
    </>
  );
}
