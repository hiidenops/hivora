"""Template icons: downloaded once from the template's source, then served locally.

The browser never contacts third parties. Only PNG, JPEG, WebP, GIF and SVG are
kept, size-capped and checked by their magic bytes; SVG is served sandboxed.
"""

import asyncio
import hashlib
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from hivora import __version__
from hivora.templates.catalog import CatalogEntry

if TYPE_CHECKING:
    import aiohttp

logger = logging.getLogger(__name__)

MAX_BYTES = 512 * 1024
USER_AGENT = f"Hivora/{__version__} (+https://github.com/hiidenops/hivora)"
MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}


def sniff(data: bytes) -> str | None:
    """File extension from content, never from the server's claims."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    head = data[:512].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in data[:4096].lower():
        return "svg"
    return None


class IconCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, slug: str) -> Path | None:
        return next(iter(sorted(self.directory.glob(f"{slug}--*"))), None)

    @staticmethod
    def _stem(slug: str, url: str) -> str:
        # The source URL is part of the name: changing it triggers a new download.
        return f"{slug}--{hashlib.sha256(url.encode()).hexdigest()[:12]}"

    async def warm(self, entries: Iterable[CatalogEntry]) -> None:
        """Download missing icons; failures are logged, the UI falls back to a letter."""
        import aiohttp  # lazy: only needed while warming the cache

        self.directory.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        ) as http:
            for entry in entries:
                icon = entry.template.metadata.icon
                if icon is None:
                    continue
                url = icon.download_url
                stem = self._stem(entry.slug, url)
                if any(self.directory.glob(f"{stem}.*")):
                    continue
                try:
                    data = await fetch_capped(http, url)
                except Exception as exc:
                    logger.warning(
                        "icon download failed",
                        extra={"template": entry.slug, "url": url, "error": str(exc)},
                    )
                    continue
                ext = sniff(data)
                if ext is None:
                    logger.warning(
                        "icon rejected: unsupported content",
                        extra={"template": entry.slug, "url": url},
                    )
                    continue
                for old in self.directory.glob(f"{entry.slug}--*"):
                    old.unlink()
                (self.directory / f"{stem}.{ext}").write_bytes(data)
                await asyncio.sleep(0)


async def fetch_capped(http: "aiohttp.ClientSession", url: str) -> bytes:
    """Whole response body, refusing anything larger than MAX_BYTES."""
    async with http.get(url, allow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("icon too large")
            chunks.append(chunk)
        return b"".join(chunks)
