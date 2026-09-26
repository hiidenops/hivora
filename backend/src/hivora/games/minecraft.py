"""Minecraft specifics: the `list` answer parser and the official version list.

Everything else (players, lists, worlds) is generic: see `games.engine`.
"""

import re
from typing import Any

# "There are 2 of a max of 20 players online: a, b" (recent) or "There are 2/20 ..." (old)
_LIST = re.compile(r"There are (\d+)\s*(?:of a max of|/)\s*(\d+) players online:?\s*(.*)", re.S)
_FORMATTING = re.compile(r"§.|\x1b\[[0-9;]*m")


def clean(text: str) -> str:
    return _FORMATTING.sub("", text).strip()


def parse_list(text: str) -> tuple[int, int, list[str]]:
    """Answer of `list`: (online, max, names). ValueError if unrecognized."""
    m = _LIST.search(clean(text))
    if not m:
        raise ValueError(f"unexpected answer to 'list': {clean(text)[:200]}")
    names = [n.strip() for n in m.group(3).replace("\n", ",").split(",") if n.strip()]
    return int(m.group(1)), int(m.group(2)), names


MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
VERSIONS_TTL_S = 3600.0


class MinecraftVersions:
    """Official version list (Mojang manifest), cached for an hour."""

    def __init__(self, url: str = MOJANG_MANIFEST) -> None:
        self.url = url
        self._cache: tuple[float, dict[str, Any]] | None = None

    async def _manifest(self) -> dict[str, Any]:
        import time

        import aiohttp

        from hivora.games.modpacks import USER_AGENT, ModpackSourceError

        if self._cache and time.monotonic() - self._cache[0] < VERSIONS_TTL_S:
            return self._cache[1]
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10), headers={"User-Agent": USER_AGENT}
                ) as http,
                http.get(self.url) as r,
            ):
                r.raise_for_status()
                data: dict[str, Any] = await r.json()
        except Exception as exc:
            raise ModpackSourceError(f"Mojang version list unavailable: {exc}") from exc
        self._cache = (time.monotonic(), data)
        return data

    async def options(self, *, snapshots: bool) -> list[dict[str, str]]:
        data = await self._manifest()
        kinds = {"release", "snapshot"} if snapshots else {"release"}
        return [
            {"value": "LATEST", "label": f"latest ({data['latest']['release']})"},
            {"value": "SNAPSHOT", "label": f"snapshot ({data['latest']['snapshot']})"},
            *({"value": v["id"], "label": v["id"]} for v in data["versions"] if v["type"] in kinds),
        ]
