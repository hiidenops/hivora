from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import BaseTestServer, TestServer

from hivora.templates import Catalog
from hivora.templates.catalog import CatalogEntry
from hivora.templates.icons import MAX_BYTES, IconCache, sniff
from hivora.templates.schema import IconSource

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"></svg>'


@pytest.mark.parametrize(
    ("data", "ext"),
    [
        (PNG, "png"),
        (b"\xff\xd8\xff\xe0rest", "jpg"),
        (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
        (SVG, "svg"),
        (b"  <svg></svg>", "svg"),
        (b"<html><body>not an image</body></html>", None),
        (b"GIF89a", None),
    ],
)
def test_sniff_uses_content_not_headers(data: bytes, ext: str | None) -> None:
    assert sniff(data) == ext


def test_icon_source_needs_exactly_one_origin() -> None:
    assert IconSource(steam_appid=1623730).download_url.endswith("/1623730/header.jpg")
    with pytest.raises(ValueError):
        IconSource()
    with pytest.raises(ValueError):
        IconSource(url="https://a/x.png", steam_appid=1)
    with pytest.raises(ValueError):
        IconSource(url="http://insecure/x.png")


@pytest.fixture
async def server() -> AsyncIterator[BaseTestServer]:
    async def ok(_: web.Request) -> web.Response:
        return web.Response(body=PNG, content_type="text/html")  # lying content type

    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<html></html>")

    async def huge(_: web.Request) -> web.Response:
        return web.Response(body=PNG + b"\0" * MAX_BYTES)

    app = web.Application()
    app.router.add_get("/ok.png", ok)
    app.router.add_get("/page.html", page)
    app.router.add_get("/huge.png", huge)
    async with TestServer(app) as srv:
        yield srv


def entry_with_icon(catalog: Catalog, slug: str, url: str) -> CatalogEntry:
    entry = catalog.get(slug)
    metadata = entry.template.metadata.model_copy(
        update={"icon": IconSource.model_construct(url=url)}
    )
    template = entry.template.model_copy(update={"metadata": metadata})
    return CatalogEntry(template, entry.manifest, entry.checksum, entry.source)


async def test_warm_keeps_valid_icons_only(
    tmp_path: Path, catalog: Catalog, server: TestServer
) -> None:
    cache = IconCache(tmp_path)
    entries = [
        entry_with_icon(catalog, "vaultwarden", str(server.make_url("/ok.png"))),
        entry_with_icon(catalog, "minecraft", str(server.make_url("/page.html"))),
    ]
    await cache.warm(entries)
    assert cache.path("vaultwarden") is not None and cache.path("vaultwarden").suffix == ".png"  # type: ignore[union-attr]
    assert cache.path("minecraft") is None  # HTML rejected: the UI falls back to a letter

    huge = [entry_with_icon(catalog, "minecraft", str(server.make_url("/huge.png")))]
    await cache.warm(huge)
    assert cache.path("minecraft") is None
