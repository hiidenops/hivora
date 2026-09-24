from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import BaseTestServer, TestServer

from hivora.games.modpacks import (
    CurseForgeKeyMissingError,
    ModpackCatalog,
    parse_curseforge,
    parse_modrinth,
)

MODRINTH = {"hits": [{
    "slug": "cobblemon-fabric", "title": "Cobblemon", "description": "Pokémon in Minecraft",
    "icon_url": "https://cdn.modrinth.com/data/x/icon.png", "downloads": 1234,
    "versions": ["1.20.1", "1.21.1", "24w10a", "1.19.2", "1.21.1-rc1"],
    "categories": ["fabric", "adventure"],
}]}  # fmt: skip
CURSEFORGE = {"data": [{
    "slug": "all-the-mods-9", "name": "All the Mods 9", "summary": "Kitchen sink",
    "logo": {"thumbnailUrl": "https://media.forgecdn.net/avatars/thumbnails/1.png"},
    "downloadCount": 99, "links": {"websiteUrl": "https://www.curseforge.com/minecraft/modpacks/all-the-mods-9"},
    "latestFilesIndexes": [{"gameVersion": "1.20.1", "modLoader": 1},
                           {"gameVersion": "1.20.1", "modLoader": 6}],
}]}  # fmt: skip


def test_parse_modrinth_keeps_releases_newest_first() -> None:
    [p] = parse_modrinth(MODRINTH)
    assert (p.slug, p.loaders, p.mc_versions) == (
        "cobblemon-fabric",
        ["fabric"],
        ["1.21.1", "1.20.1", "1.19.2"],
    )


def test_parse_curseforge_maps_loader_ids() -> None:
    [p] = parse_curseforge(CURSEFORGE)
    assert (p.slug, p.loaders, p.mc_versions) == (
        "all-the-mods-9",
        ["forge", "neoforge"],
        ["1.20.1"],
    )


@pytest.fixture
async def fake_apis() -> AsyncIterator[tuple[BaseTestServer, list[dict[str, str]]]]:
    seen: list[dict[str, str]] = []

    async def modrinth(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response(MODRINTH)

    async def curseforge(request: web.Request) -> web.Response:
        if request.headers.get("x-api-key") != "good-key":
            return web.Response(status=403)
        seen.append(dict(request.query))
        return web.json_response(CURSEFORGE)

    app = web.Application()
    app.router.add_get("/v2/search", modrinth)
    app.router.add_get("/v1/mods/search", curseforge)
    async with TestServer(app) as srv:
        yield srv, seen


async def test_search_both_sources_with_cache(
    tmp_path: Path, fake_apis: tuple[BaseTestServer, list[dict[str, str]]]
) -> None:
    server, seen = fake_apis
    base = str(server.make_url(""))
    catalog = ModpackCatalog(tmp_path, modrinth_api=f"{base}/v2", curseforge_api=f"{base}/v1")
    first = await catalog.search("modrinth", "cobble", loader="fabric", mc_version="1.21.1")
    again = await catalog.search("modrinth", "cobble", loader="fabric", mc_version="1.21.1")
    assert first == again and len(seen) == 1  # second call served from cache
    assert '"categories:fabric"' in seen[0]["facets"]

    with pytest.raises(CurseForgeKeyMissingError):
        await catalog.search("curseforge", "atm")  # no key configured
    with pytest.raises(CurseForgeKeyMissingError):
        await catalog.search("curseforge", "atm", curseforge_key="bad")
    [pack] = await catalog.search("curseforge", "atm", loader="neoforge", curseforge_key="good-key")
    assert pack.slug == "all-the-mods-9" and seen[-1]["modLoaderType"] == "6"


async def test_icon_relay_only_from_known_cdns(tmp_path: Path) -> None:
    from hivora.core.errors import ValidationError

    catalog = ModpackCatalog(tmp_path)
    for url in ("https://evil.example/x.png", "http://cdn.modrinth.com/x.png"):
        with pytest.raises(ValidationError):
            await catalog.icon(url)


async def test_fetch_capped_reads_the_whole_body() -> None:
    import aiohttp

    from hivora.templates.icons import MAX_BYTES, fetch_capped

    big = b"\x89PNG\r\n\x1a\n" + b"\0" * 300_000

    async def dribble(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse()
        await resp.prepare(request)
        for i in range(0, len(big), 10_000):  # many small network chunks
            await resp.write(big[i : i + 10_000])
        return resp

    async def huge(request: web.Request) -> web.Response:
        return web.Response(body=b"\0" * (MAX_BYTES + 1))

    app = web.Application()
    app.router.add_get("/i.png", dribble)
    app.router.add_get("/huge", huge)
    async with TestServer(app) as srv, aiohttp.ClientSession() as http:
        assert await fetch_capped(http, str(srv.make_url("/i.png"))) == big
        with pytest.raises(ValueError):
            await fetch_capped(http, str(srv.make_url("/huge")))
