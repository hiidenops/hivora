"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { useSession } from "@/components/app-shell";
import { IntegrationsCard } from "@/features/account/integrations-card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { TileSkeletons } from "@/components/ui/skeleton";
import { api, ApiError, type Modpack } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Source = "modrinth" | "curseforge";
const LOADERS = ["fabric", "forge", "neoforge", "quilt"] as const;

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Deploy link: the Minecraft wizard, prefilled for this pack. */
function deployHref(p: Modpack): string {
  const q = new URLSearchParams({ template: "minecraft", name: p.title.slice(0, 60), memory: "6G" });
  if (p.source === "modrinth") {
    q.set("server_type", "MODRINTH");
    q.set("modrinth_modpack", p.slug);
  } else {
    q.set("server_type", "AUTO_CURSEFORGE");
    q.set("cf_modpack", p.slug);
  }
  return `/deploy/?${q}`;
}

export function ModpackBrowser() {
  const { t, lang, errorMessage } = useI18n();
  const { can } = useSession();
  const [source, setSource] = useState<Source>("modrinth");
  const [query, setQuery] = useState("");
  const [loader, setLoader] = useState("");
  const [version, setVersion] = useState("");
  const q = useDebounced(query);
  const v = useDebounced(version);
  const validVersion = /^\d+\.\d+(\.\d+)?$/.test(v) ? v : "";

  const search = useInfiniteQuery({
    queryKey: ["modpacks", source, q, loader, validVersion],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<Modpack[]>("/modpacks/search", {
        query: {
          source, q, page: String(pageParam),
          ...(loader ? { loader } : {}), ...(validVersion ? { mc_version: validVersion } : {}),
        },
      }),  // prettier-ignore
    getNextPageParam: (last, pages) => (last.length >= 24 ? pages.length : undefined),
    staleTime: 60_000,
    placeholderData: (previous) => previous, // keep results on screen while typing
  });
  const packs = search.data?.pages.flat() ?? [];
  const noKey = search.error instanceof ApiError && search.error.code === "curseforge_key_missing";
  const fmt = new Intl.NumberFormat(lang, { notation: "compact" });

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3 shadow-xs">
        <div role="tablist" aria-label={t("modpacks.source")} className="inline-flex rounded-md border bg-card p-0.5">
          {(["modrinth", "curseforge"] as Source[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={source === s}
              onClick={() => setSource(s)}
              className={cn(
                "rounded px-3 py-1.5 text-sm transition-colors",
                source === s ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {s === "modrinth" ? "Modrinth" : "CurseForge"}
            </button>
          ))}
        </div>
        <Input
          className="w-64"
          placeholder={t("modpacks.search")}
          aria-label={t("modpacks.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="grid gap-1">
          <Label htmlFor="mp-loader" className="text-xs text-muted-foreground">
            {t("modpacks.loader")}
          </Label>
          <Select id="mp-loader" className="w-36" value={loader} onChange={(e) => setLoader(e.target.value)}>
            <option value="">{t("modpacks.anyLoader")}</option>
            {LOADERS.map((l) => (
              <option key={l} value={l}>
                {l[0].toUpperCase() + l.slice(1)}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="mp-version" className="text-xs text-muted-foreground">
            {t("modpacks.version")}
          </Label>
          <Input
            id="mp-version"
            className="w-32 font-mono"
            placeholder={t("modpacks.anyVersion")}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </div>
      </div>

      {noKey ? (
        can("admin") ? (
          <div className="grid max-w-2xl gap-4 rounded-lg border border-warn/50 bg-card p-4 shadow-xs">
            <p className="text-sm">
              {t("modpacks.noKeyAdmin")}{" "}
              <a href="https://console.curseforge.com/" target="_blank" rel="noreferrer" className="underline">
                console.curseforge.com
              </a>
            </p>
            <IntegrationsCard />
          </div>
        ) : (
          <Alert tone="warn">{t("modpacks.noKey")}</Alert>
        )
      ) : search.error ? (
        <Alert tone="danger">{errorMessage(search.error)}</Alert>
      ) : null}
      {search.isPending && <TileSkeletons label={t("common.loading")} count={6} />}
      {search.isSuccess && packs.length === 0 && <p className="text-muted-foreground">{t("modpacks.empty")}</p>}

      <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-4">
        {packs.map((p, i) => (
          <Card
            key={`${p.source}:${p.slug}`}
            role="article"
            aria-label={p.title}
            className="card-interactive animate-enter flex flex-col gap-3 p-5"
            style={{ animationDelay: `${Math.min(i % 24, 10) * 30}ms` }}
          >
            <div className="flex items-center gap-3">
              <AppIcon src={p.icon_url} name={p.title} className="size-12" />
              <div className="min-w-0">
                <div className="truncate font-medium">{p.title}</div>
                <div className="text-xs text-muted-foreground">
                  {t("modpacks.downloads", { count: fmt.format(p.downloads) })}
                </div>
              </div>
            </div>
            <p className="line-clamp-3 flex-1 text-sm text-muted-foreground">{p.summary}</p>
            <div className="flex flex-wrap gap-1">
              {p.loaders.map((l) => (
                <Badge key={l}>{l}</Badge>
              ))}
              {p.mc_versions.map((mv) => (
                <Badge key={mv} className="font-mono">
                  {mv}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {can("operator") && (
                <Button asChild size="sm">
                  <Link href={deployHref(p)}>{t("modpacks.deploy")}</Link>
                </Button>
              )}
              <Button asChild size="sm" variant="ghost">
                <a href={p.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> {t("modpacks.open")}
                </a>
              </Button>
            </div>
          </Card>
        ))}
      </div>
      {search.hasNextPage && (
        <Button
          variant="outline"
          className="justify-self-center"
          disabled={search.isFetchingNextPage}
          onClick={() => void search.fetchNextPage()}
        >
          {t("modpacks.more")}
        </Button>
      )}
    </div>
  );
}
