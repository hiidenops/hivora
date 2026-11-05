"use client";

import { Globe } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useI18n } from "@/lib/i18n";

// React Flow: loaded when the map opens (page budget).
const DnsMap = dynamic(() => import("./dns-map").then((m) => m.DnsMap), { ssr: false });

/** The VPN's own DNS, as a map of its names and the apps of its zones. */
export function DnsDialog({ appId, vpnName }: { appId: number; vpnName: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button size="sm" variant="outline">
          <Globe /> {t("dns.open")}
        </Button>
      </SheetTrigger>
      <SheetContent title={t("dns.title", { vpn: vpnName })} icon={<Globe className="size-5" />} closeLabel={t("common.close")} resizeLabel={t("common.resize")} widthKey="dns" className="sm:max-w-5xl">
        <p className="mb-3 text-sm text-muted-foreground">{t("dns.help")}</p>
        {open && <DnsMap appId={appId} />}
      </SheetContent>
    </Sheet>
  );
}
