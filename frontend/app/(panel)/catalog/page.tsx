"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { PageHeader, useSession } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TileSkeletons } from "@/components/ui/skeleton";
import { ModpackBrowser } from "@/features/modpacks/modpack-browser";
import { useSystemInfo, useTemplates } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function AppsCatalog() {
  const { t, l } = useI18n();
  const { can } = useSession();
  const { data: templates, isPending } = useTemplates();
  const { data: system } = useSystemInfo();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");

  const categories = useMemo(() => ["all", ...new Set((templates ?? []).map((tp) => tp.category))], [templates]);
  const visible = (templates ?? []).filter((tp) => {
    const q = query.trim().toLowerCase();
    const text = `${tp.name} ${l(tp.description)} ${tp.tags.join(" ")}`.toLowerCase();
    return (category === "all" || tp.category === category) && (!q || text.includes(q));
  });

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3 shadow-xs">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={cn(
              "rounded-full border px-3 py-1 text-sm transition-colors",
              category === c
                ? "border-primary bg-primary font-medium text-primary-foreground"
                : "bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t(`catalog.category.${c}` as MessageKey)}
          </button>
        ))}
        {system && (
          <Badge className="ml-auto" title={t("catalog.hostArchHelp")}>
            {t("catalog.hostArch", { arch: t(`arch.${system.arch}` as MessageKey) })}
          </Badge>
        )}
        <Input
          className={system ? "w-64" : "ml-auto w-64"}
          placeholder={t("catalog.search")}
          aria-label={t("catalog.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {isPending && <TileSkeletons label={t("common.loading")} count={4} />}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-4">
        {visible.map((tp, i) => (
          <Card
            key={tp.slug}
            role="article"
            aria-label={tp.name}
            className="card-interactive animate-enter flex flex-col gap-3 p-5"
            style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}
          >
            <div className="flex items-center gap-3">
              <AppIcon src={tp.icon_url} name={tp.name} className="size-12" />
              <div>
                <div className="font-medium">{tp.name}</div>
                <div className="font-mono text-xs text-muted-foreground">v{tp.version}</div>
              </div>
            </div>
            <p className="flex-1 text-sm text-muted-foreground">{l(tp.description)}</p>
            <div className="flex flex-wrap gap-1">
              {tp.tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
            {!tp.compatible ? (
              <Badge className="self-start border-warn/50 text-warn" title={t("catalog.incompatibleHelp")}>
                {tp.arch.length === 1 ? t(`catalog.only.${tp.arch[0]}` as MessageKey) : t("catalog.incompatible")}
              </Badge>
            ) : (
              can("operator") && (
                <Button asChild className="self-start">
                  <Link href={`/deploy/?template=${tp.slug}`}>{t("action.deploy")}</Link>
                </Button>
              )
            )}
          </Card>
        ))}
      </div>
    </>
  );
}

function Catalog() {
  const { t } = useI18n();
  const router = useRouter();
  const tab = useSearchParams().get("tab") === "modpacks" ? "modpacks" : "apps";
  return (
    <>
      <PageHeader title={t("catalog.title")} />
      <div role="tablist" className="mb-5 flex gap-1 rounded-lg border bg-card p-1 shadow-xs">
        {(["apps", "modpacks"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => router.replace(k === "apps" ? "/catalog/" : "/catalog/?tab=modpacks")}
            className={cn(
              "rounded-md px-4 py-2 text-sm transition-colors",
              tab === k
                ? "bg-primary font-medium text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t(k === "apps" ? "catalog.tab.apps" : "catalog.tab.modpacks")}
          </button>
        ))}
      </div>
      {tab === "apps" ? <AppsCatalog /> : <ModpackBrowser />}
    </>
  );
}

export default function CatalogPage() {
  return (
    <Suspense>
      <Catalog />
    </Suspense>
  );
}
