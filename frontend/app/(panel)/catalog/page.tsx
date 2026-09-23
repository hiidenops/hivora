"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useTemplates } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function CatalogPage() {
  const { t, l } = useI18n();
  const { can } = useSession();
  const { data: templates, isPending } = useTemplates();
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
      <PageHeader
        title={t("catalog.title")}
        actions={
          <Input
            className="w-64"
            placeholder={t("catalog.search")}
            aria-label={t("catalog.search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        }
      />
      <div className="mb-5 flex flex-wrap gap-2">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={cn(
              "rounded-full border px-3 py-1 text-sm",
              category === c ? "border-primary bg-primary/15 font-medium" : "text-muted-foreground hover:bg-muted",
            )}
          >
            {t(`catalog.category.${c}` as MessageKey)}
          </button>
        ))}
      </div>
      {isPending && <p className="text-muted-foreground">{t("common.loading")}</p>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-4">
        {visible.map((tp) => (
          <Card key={tp.slug} role="article" aria-label={tp.name} className="flex flex-col gap-3 p-5">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-lg bg-muted font-semibold">{tp.name[0]}</span>
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
              <Badge className="self-start border-warn/50 text-warn">{t("catalog.incompatible")}</Badge>
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
