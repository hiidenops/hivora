"""Minecraft server tools: players online, whitelist and operators.

Commands go through `rcon-cli` inside the container (exec, no shell, strict
player names). Lists are read from the server's own files through the bind
mount. Turning the whitelist on/off is intent: a template setting, applied by
a new revision (the image rewrites `white-list` on every start).
"""

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hivora.core.errors import ConflictError, HivoraError, ValidationError
from hivora.docker_gateway import ContainerInfo
from hivora.jobs import Job
from hivora.runtime import Runtime

PLAYER_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")
# "There are 2 of a max of 20 players online: a, b" (recent) or "There are 2/20 ..." (old)
_LIST = re.compile(r"There are (\d+)\s*(?:of a max of|/)\s*(\d+) players online:?\s*(.*)", re.S)
_FORMATTING = re.compile(r"§.|\x1b\[[0-9;]*m")
_FAILURES = ("does not exist", "could not", "unknown", "error", "incorrect")
RCON_TIMEOUT_S = 15


class NotMinecraftError(ConflictError):
    code = "not_minecraft"


class ServerNotRunningError(ConflictError):
    code = "server_not_running"


class GameCommandError(HivoraError):
    code = "game_command_failed"


@dataclass(frozen=True, slots=True)
class Players:
    running: bool
    online: int | None
    max: int | None
    names: list[str]


def clean(text: str) -> str:
    return _FORMATTING.sub("", text).strip()


def parse_list(text: str) -> tuple[int, int, list[str]]:
    m = _LIST.search(clean(text))
    if not m:
        raise GameCommandError("unexpected answer to 'list'", output=clean(text)[:200])
    names = [n.strip() for n in m.group(3).replace("\n", ",").split(",") if n.strip()]
    return int(m.group(1)), int(m.group(2)), names


def valid_name(name: str) -> str:
    if not PLAYER_NAME.match(name):
        raise ValidationError("invalid player name", field="name")
    return name


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


class MinecraftTools:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def _server(self, app_id: int) -> tuple[str, Path | None, ContainerInfo | None]:
        async with self.rt.sessions() as session:
            app, entry, container = await self.rt.apps.main_container(session, app_id)
            game = entry.template.game if entry else None
            if not game or game.query != "minecraft":
                raise NotMinecraftError("not a Minecraft server", slug=app.slug)
            data = next(
                (Path(v.source) for s in app.services for v in s.volumes if v.target == "/data"),
                None,
            )
        return app.slug, data, container

    async def _rcon(self, container: ContainerInfo | None, *args: str) -> str:
        if container is None:
            raise ServerNotRunningError("the server must be running")
        async with asyncio.timeout(RCON_TIMEOUT_S):
            code, out = await self.rt.gateway.exec_run(container.id, ["rcon-cli", *args])
        text = clean(out)
        if code != 0 or any(f in text.lower() for f in _FAILURES):
            raise GameCommandError(text or f"rcon-cli exited with {code}")
        return text

    async def players(self, app_id: int) -> Players:
        _, _, container = await self._server(app_id)
        if container is None:
            return Players(False, None, None, [])
        online, maximum, names = parse_list(await self._rcon(container, "list"))
        return Players(True, online, maximum, names)

    async def access(self, app_id: int) -> dict[str, Any]:
        _, data, container = await self._server(app_id)
        async with self.rt.sessions() as session:
            settings = await self.rt.apps.current_settings(session, app_id)
        whitelist = _read_json_list(data / "whitelist.json") if data else []
        ops = _read_json_list(data / "ops.json") if data else []
        return {
            "running": container is not None,
            "whitelist_enabled": bool(settings.values.get("enable_whitelist", False)),
            "whitelist": sorted(str(e.get("name", "")) for e in whitelist if e.get("name")),
            "ops": sorted(
                (
                    {"name": str(e["name"]), "level": int(e.get("level", 4))}
                    for e in ops
                    if e.get("name")
                ),
                key=lambda o: str(o["name"]).lower(),
            ),
        }

    async def whitelist(self, app_id: int, name: str, *, add: bool) -> str:
        slug, _, container = await self._server(app_id)
        out = await self._rcon(container, "whitelist", "add" if add else "remove", valid_name(name))
        self.rt.bus.publish("game.whitelist_added" if add else "game.whitelist_removed",
                            app=slug, target=name)  # fmt: skip
        return out

    async def operator(self, app_id: int, name: str, *, add: bool) -> str:
        slug, _, container = await self._server(app_id)
        out = await self._rcon(container, "op" if add else "deop", valid_name(name))
        self.rt.bus.publish("game.op_added" if add else "game.op_removed", app=slug, target=name)
        return out

    async def set_whitelist_enabled(self, app_id: int, enabled: bool) -> Job:
        await self._server(app_id)
        async with self.rt.sessions() as session:
            settings = await self.rt.apps.current_settings(session, app_id)
        return await self.rt.apps.update(app_id, {**settings.values, "enable_whitelist": enabled})


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
