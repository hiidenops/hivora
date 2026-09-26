"""Public branches of a Steam dedicated server (versions a template lets you pick).

Read from api.steamcmd.net (Steam's app info as JSON), cached for an hour;
password-protected branches are left out.
"""

import time
from typing import Any

import aiohttp

from hivora.games.modpacks import USER_AGENT, ModpackSourceError

STEAMCMD_INFO = "https://api.steamcmd.net/v1/info/{appid}"
TTL_S = 3600.0


def parse_branches(appid: str, data: dict[str, Any]) -> list[dict[str, str]]:
    branches = data["data"][appid]["depots"]["branches"]
    public = {k: v for k, v in branches.items() if not v.get("pwdrequired")}

    def order(name: str) -> tuple[int, int, str]:  # public first, then newest builds
        return (name != "public", -int(public[name].get("buildid") or 0), name)

    return [
        {"value": name, "label": f"{name} — {desc}" if (desc := public[name].get("description"))
         else name}
        for name in sorted(public, key=order)
    ]  # fmt: skip


class SteamBranches:
    def __init__(self, url: str = STEAMCMD_INFO) -> None:
        self.url = url
        self._cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

    async def options(self, appid: str) -> list[dict[str, str]]:
        hit = self._cache.get(appid)
        if hit and time.monotonic() - hit[0] < TTL_S:
            return hit[1]
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10), headers={"User-Agent": USER_AGENT}
                ) as http,
                http.get(self.url.format(appid=appid)) as r,
            ):
                r.raise_for_status()
                found = parse_branches(appid, await r.json())
        except Exception as exc:
            raise ModpackSourceError(f"Steam branch list unavailable: {exc}") from exc
        self._cache[appid] = (time.monotonic(), found)
        return found
