"""Minecraft modpack search on Modrinth and CurseForge, through Hivora.

The browser never calls these services: Hivora queries them (honest
User-Agent, short in-memory cache) and relays pack icons from their CDNs only.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import aiohttp

from hivora import __version__
from hivora.core.errors import HivoraError, ValidationError
from hivora.templates.icons import fetch_capped, sniff

Source = Literal["modrinth", "curseforge"]
Loader = Literal["fabric", "forge", "neoforge", "quilt"]

USER_AGENT = f"Hivora/{__version__} (+https://github.com/hiidenops/hivora)"
MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CF_MINECRAFT = 432
CF_MODPACKS = 4471
CF_LOADERS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
ICON_HOSTS = frozenset({"cdn.modrinth.com", "media.forgecdn.net"})
CACHE_TTL_S = 60.0
PAGE_SIZE = 24


class ModpackSourceError(HivoraError):
    code = "modpack_source_unavailable"


class CurseForgeKeyMissingError(ValidationError):
    code = "curseforge_key_missing"


@dataclass(frozen=True, slots=True)
class Modpack:
    source: Source
    slug: str
    title: str
    summary: str
    icon: str | None  # third-party URL, served through /modpacks/icon
    downloads: int
    mc_versions: list[str]  # newest first, a few
    loaders: list[str]
    url: str


def _versions(values: list[str], limit: int = 4) -> list[str]:
    releases = [v for v in values if v[:1].isdigit() and "-" not in v and "w" not in v]

    def key(v: str) -> tuple[int, ...]:
        return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))

    return sorted(set(releases), key=key, reverse=True)[:limit]


def parse_modrinth(data: dict[str, Any]) -> list[Modpack]:
    known = {"fabric", "forge", "neoforge", "quilt"}
    return [
        Modpack(
            source="modrinth", slug=h["slug"], title=h["title"], summary=h.get("description", ""),
            icon=h.get("icon_url") or None, downloads=int(h.get("downloads", 0)),
            mc_versions=_versions(h.get("versions", [])),
            loaders=sorted(known & set(h.get("categories", []))),
            url=f"https://modrinth.com/modpack/{h['slug']}",
        )
        for h in data.get("hits", [])
    ]  # fmt: skip


def parse_curseforge(data: dict[str, Any]) -> list[Modpack]:
    names = {v: k for k, v in CF_LOADERS.items()}
    packs = []
    for m in data.get("data", []):
        files = m.get("latestFilesIndexes", [])
        packs.append(Modpack(
            source="curseforge", slug=m["slug"], title=m["name"], summary=m.get("summary", ""),
            icon=(m.get("logo") or {}).get("thumbnailUrl") or None,
            downloads=int(m.get("downloadCount", 0)),
            mc_versions=_versions([f.get("gameVersion", "") for f in files]),
            loaders=sorted({names[f["modLoader"]] for f in files if f.get("modLoader") in names}),
            url=(m.get("links") or {}).get("websiteUrl")
            or f"https://www.curseforge.com/minecraft/modpacks/{m['slug']}",
        ))  # fmt: skip
    return packs


class ModpackCatalog:
    def __init__(self, icon_dir: Path, *, modrinth_api: str = MODRINTH_API,
                 curseforge_api: str = CURSEFORGE_API) -> None:  # fmt: skip
        self.icon_dir = icon_dir
        self.modrinth_api = modrinth_api
        self.curseforge_api = curseforge_api
        # ponytail: unbounded-by-time dict pruned by size; fine for one admin's searches.
        self._cache: dict[str, tuple[float, list[Modpack]]] = {}

    async def _get_json(self, url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers={"User-Agent": USER_AGENT, **headers}
            ) as http:
                async with http.get(url, params=params) as r:
                    if r.status in (401, 403):
                        raise CurseForgeKeyMissingError("the CurseForge API key was refused")
                    r.raise_for_status()
                    return await r.json()
        except HivoraError:
            raise
        except Exception as exc:
            raise ModpackSourceError(f"{urlsplit(url).hostname} unavailable: {exc}") from exc

    async def search(
        self, source: Source, query: str, *, loader: Loader | None = None,
        mc_version: str | None = None, page: int = 0, curseforge_key: str | None = None,
    ) -> list[Modpack]:  # fmt: skip
        cache_key = json.dumps([source, query, loader, mc_version, page])
        hit = self._cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        if source == "modrinth":
            facets = [["project_type:modpack"]]
            if loader:
                facets.append([f"categories:{loader}"])
            if mc_version:
                facets.append([f"versions:{mc_version}"])
            data = await self._get_json(f"{self.modrinth_api}/search", {
                "query": query, "facets": json.dumps(facets), "limit": str(PAGE_SIZE),
                "offset": str(page * PAGE_SIZE), "index": "relevance" if query else "downloads",
            }, {})  # fmt: skip
            packs = parse_modrinth(data)
        else:
            if not curseforge_key:
                raise CurseForgeKeyMissingError("set a CurseForge API key in Settings")
            params = {
                "gameId": str(CF_MINECRAFT), "classId": str(CF_MODPACKS), "searchFilter": query,
                "sortField": "2", "sortOrder": "desc", "pageSize": str(PAGE_SIZE),
                "index": str(page * PAGE_SIZE),
            }  # fmt: skip
            if loader:
                params["modLoaderType"] = str(CF_LOADERS[loader])
            if mc_version:
                params["gameVersion"] = mc_version
            data = await self._get_json(f"{self.curseforge_api}/mods/search", params,
                                        {"x-api-key": curseforge_key})  # fmt: skip
            packs = parse_curseforge(data)
        if len(self._cache) > 200:
            self._cache.clear()
        self._cache[cache_key] = (time.monotonic(), packs)
        return packs

    async def icon(self, url: str) -> tuple[Path, str]:
        """Cached copy of a pack icon; only from the two CDNs, size-capped, sniffed."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ICON_HOSTS:
            raise ValidationError("icon host not allowed", url=url)
        stem = hashlib.sha256(url.encode()).hexdigest()[:24]
        self.icon_dir.mkdir(parents=True, exist_ok=True)
        cached = next(iter(self.icon_dir.glob(f"{stem}.*")), None)
        if cached:
            return cached, cached.suffix[1:]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        ) as http:
            try:
                # The whole body: a single read() returned the first chunk only,
                # which cached truncated icons.
                data = await fetch_capped(http, url)
            except (aiohttp.ClientError, ValueError) as exc:
                raise ValidationError("icon unavailable", url=url) from exc
        ext = sniff(data)
        if ext is None or ext == "svg":
            raise ValidationError("icon rejected", url=url)
        path = self.icon_dir / f"{stem}.{ext}"
        path.write_bytes(data)
        return path, ext
