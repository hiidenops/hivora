"use client";

import { AppWindow, ArrowLeft, Container, Gamepad2 } from "lucide-react";
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

type Kind = "games" | "apps";
const isGame = (category: string) => category === "games";

/** Landing: two big doors, each showing real icons from its side of the catalog. */
function CatalogHome() {
  const { t } = useI18n();
  const { data: templates } = useTemplates();
  const doors: { kind: Kind; icon: typeof Gamepad2 }[] = [
    { kind: "games", icon: Gamepad2 },
    { kind: "apps", icon: AppWindow },
  ];
  return (
    <div className="stagger grid gap-5 md:grid-cols-2">
      {doors.map(({ kind, icon: Icon }) => {
        const items = (templates ?? []).filter((tp) => isGame(tp.category) === (kind === "games"));
        return (
          <Link
            key={kind}
            href={`/catalog/?kind=${kind}`}
            className="surface card-interactive grid min-h-64 content-between gap-8 rounded-2xl border p-8"
          >
            <div className="flex -space-x-3">
              {items.slice(0, 6).map((tp) => (
                <AppIcon key={tp.slug} src={tp.icon_url} name={tp.name} className="size-14 rounded-xl ring-4 ring-card" />
              ))}
            </div>
            <div className="grid gap-2">
              <h2 className="flex items-center gap-3 text-3xl font-semibold tracking-tight">
                <Icon className="size-7 text-warn" /> {t(`catalog.home.${kind}` as MessageKey)}
              </h2>
              <p className="text-muted-foreground">{t(`catalog.home.${kind}.text` as MessageKey)}</p>
              <p className="text-sm font-medium">{t("catalog.count", { n: items.length })}</p>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function AppsCatalog({ kind }: { kind: Kind }) {
  const { t, l } = useI18n();
  const { can } = useSession();
  const { data: templates, isPending } = useTemplates();
  const { data: system } = useSystemInfo();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");

  const ofKind = useMemo(
    () => (templates ?? []).filter((tp) => isGame(tp.category) === (kind === "games")),
    [templates, kind],
  );
  const categories = useMemo(() => ["all", ...new Set(ofKind.map((tp) => tp.category))], [ofKind]);
  const visible = ofKind.filter((tp) => {
    const q = query.trim().toLowerCase();
    const text = `${tp.name} ${l(tp.description)} ${tp.tags.join(" ")}`.toLowerCase();
    return (category === "all" || tp.category === category) && (!q || text.includes(q));
  });

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-lg border surface p-3">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={cn(
              "rounded-full border px-3 py-1 text-sm transition-colors",
              category === c
                ? "btn-solid border-primary font-medium text-primary-foreground [--btn:var(--primary)]"
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
  const params = useSearchParams();
  const tab = params.get("tab") === "modpacks" ? "modpacks" : "apps";
  const kind = tab === "modpacks" ? "games" : params.get("kind");
  if (kind !== "games" && kind !== "apps") {
    return (
      <>
        <PageHeader title={t("catalog.title")} />
        <CatalogHome />
      </>
    );
  }
  const back = (
    <Button variant="outline" asChild>
      <Link href="/catalog/">
        <ArrowLeft /> {t("catalog.backHome")}
      </Link>
    </Button>
  );
  if (kind === "apps") {
    return (
      <>
        <PageHeader
          title={t("catalog.home.apps")}
          actions={
            <>
              <Button variant="outline" asChild>
                <Link href="/custom/">
                  <Container /> {t("custom.open")}
                </Link>
              </Button>
              {back}
            </>
          }
        />
        <AppsCatalog kind="apps" />
      </>
    );
  }
  return (
    <>
      <PageHeader title={t("catalog.home.games")} actions={back} />
      <div role="tablist" className="mb-5 flex gap-1 rounded-lg border surface p-1">
        {(["apps", "modpacks"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => router.replace(k === "apps" ? "/catalog/?kind=games" : "/catalog/?tab=modpacks")}
            className={cn(
              "relative overflow-hidden rounded-md px-4 py-2 text-sm transition-colors duration-200",
              tab === k
                ? "btn-solid font-medium text-primary-foreground [--btn:var(--primary)]"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t(k === "apps" ? "catalog.tab.servers" : "catalog.tab.modpacks")}
          </button>
        ))}
      </div>
      {tab === "apps" ? <AppsCatalog kind="games" /> : <ModpackBrowser />}
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
