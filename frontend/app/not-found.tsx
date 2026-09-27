"use client";

import Link from "next/link";

import { Brand } from "@/components/brand";
import { ShelfCat } from "@/components/shelf-cat";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

/** Served for any unknown address (static export: /404.html). */
export default function NotFound() {
  const { t } = useI18n();
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <div className="surface animate-enter grid w-full max-w-sm justify-items-center gap-6 rounded-xl border p-8 text-center">
        <Brand />
        <p className="text-7xl font-semibold leading-none tracking-tight text-warn">404</p>
        <div className="grid gap-2">
          <h1 className="text-xl font-semibold">{t("notFound.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("notFound.text")}</p>
        </div>
        <div className="w-full">
          <ShelfCat />
        </div>
        <Button asChild>
          <Link href="/">{t("notFound.back")}</Link>
        </Button>
      </div>
    </main>
  );
}
