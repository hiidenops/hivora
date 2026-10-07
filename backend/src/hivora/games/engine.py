"""Game server tools driven by the template's `game` section.

Players come from a command run in the server (rcon-cli...) or a Steam A2S
query; player lists live in the server's files and change through the
server's own commands when declared (exec, no shell, strict names), else by
editing the file; worlds are folders or files of the saves volume. Turning a
list on/off, or switching the active world, is intent: a new revision.
"""

import asyncio
import json
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.service import AppService
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, HivoraError, NotFoundError, ValidationError
from hivora.core.events import EventBus
from hivora.core.fs import confined
from hivora.docker_gateway import ContainerInfo, DockerGateway
from hivora.games import worlds as w
from hivora.games.a2s import A2SError, query_async
from hivora.games.minecraft import clean, parse_list
from hivora.jobs import Job, JobKind, JobQueue
from hivora.templates.schema import Game, GameList, GameSaves

_FAILURES = ("does not exist", "could not", "unknown", "error", "incorrect")
COMMAND_TIMEOUT_S = 15


class NotAGameServerError(ConflictError):
    code = "not_a_game_server"


class GameFeatureMissingError(NotFoundError):
    code = "game_feature_missing"


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


@dataclass(frozen=True, slots=True)
class ListEntry:
    name: str
    extra: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerList:
    id: str
    label: Any  # Localized
    editable: bool  # False: needs the server running (commands) and it is stopped
    enabled: bool | None  # None: the list cannot be turned off
    name_pattern: str
    entries: list[ListEntry]


@dataclass(frozen=True, slots=True)
class _Server:
    app_id: int
    slug: str
    game: Game
    container: ContainerInfo | None
    volumes: dict[str, Path]  # volume name -> host path (main service)
    host_ports: dict[tuple[int, str], int]  # (container port, protocol) -> published port


def read_entries(path: Path, gl: GameList) -> list[ListEntry]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if gl.format == "lines":
        names = (line.strip() for line in text.splitlines())
        return [ListEntry(n) for n in names if n and not n.startswith("//")]
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return [
        ListEntry(str(e["name"]), str(e[gl.extra_key]) if gl.extra_key in e else None)
        for e in (data if isinstance(data, list) else [])
        if isinstance(e, dict) and e.get("name")
    ]


def edit_lines(path: Path, name: str, *, add: bool) -> None:
    """Add/remove one line, keeping comments and the file's owner (edited in place)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in lines if line.strip() != name]
    if add:
        kept.append(name)
    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(kept) + ("\n" if kept else ""))


class GameTools:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], apps: AppService, settings: Settings,
        gateway: DockerGateway, bus: EventBus, jobs: JobQueue,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.apps = apps
        self.settings = settings
        self.gateway = gateway
        self.bus = bus
        self.jobs = jobs

    async def _server(self, app_id: int) -> _Server:
        async with self.sessions() as session:
            app, entry, container = await self.apps.main_container(session, app_id)
            game = entry.template.game if entry else None
            if entry is None or game is None:
                raise NotAGameServerError("not a game server", slug=app.slug)
            main = next(s for s in app.services if s.name == entry.template.main_service)
            # Template volumes are binds at <volumes_root>/<slug>/<volume name>.
            volumes = {Path(v.source).name: Path(v.source) for v in main.volumes}
            ports = {(p.container_port, p.protocol): p.host_port
                     for p in main.ports if p.host_port}  # fmt: skip
        return _Server(app_id, app.slug, game, container, volumes, ports)

    async def _values(self, app_id: int) -> dict[str, Any]:
        async with self.sessions() as session:
            return (await self.apps.planner.current_settings(session, app_id)).values

    async def _run(self, srv: _Server, cmd: list[str]) -> str:
        if srv.container is None:
            raise ServerNotRunningError("the server must be running")
        async with asyncio.timeout(COMMAND_TIMEOUT_S):
            s = self.settings
            user = f"{s.puid}:{s.pgid}" if srv.game.run_as == "app" else None
            code, out = await self.gateway.exec_run(srv.container.id, cmd, user)
        text = clean(out)
        if code != 0 or any(f in text.lower() for f in _FAILURES):
            raise GameCommandError(text or f"{cmd[0]} exited with {code}")
        return text

    # --- capabilities -----------------------------------------------------
    @staticmethod
    def capabilities(game: Game | None) -> dict[str, bool] | None:
        if game is None:
            return None
        return {
            "players": game.players is not None,
            "lists": bool(game.lists),
            "worlds": game.saves is not None,
            "world_import": bool(game.saves and not game.saves.by_file),
            "world_activate": bool(game.saves and game.saves.active_field),
        }

    # --- players ----------------------------------------------------------
    async def players(self, app_id: int) -> Players:
        srv = await self._server(app_id)
        spec = srv.game.players
        if spec is None:
            raise GameFeatureMissingError("this game does not report its players")
        if srv.container is None:
            return Players(False, None, None, [])
        if spec.command:
            out = await self._run(srv, spec.command)
            if spec.format == "csv":
                rows = [r for r in out.splitlines()[1:] if r.strip()]
                names = [r.split(",")[0].strip() for r in rows]
                return Players(True, len(rows), None, [n for n in names if n])
            try:
                online, maximum, names = parse_list(out)
            except ValueError as exc:
                raise GameCommandError(str(exc)) from exc
            return Players(True, online, maximum, names)
        port = srv.host_ports.get((spec.a2s_port or 0, "udp"))
        if port is None:
            raise GameFeatureMissingError("the A2S query port is not published")
        try:
            online, maximum, names = await query_async(self.settings.host_lan_ip or "127.0.0.1",
                                                       port)  # fmt: skip
        except A2SError as exc:  # still starting, or query disabled
            raise GameCommandError(str(exc)) from exc
        return Players(True, online, maximum, names)

    # --- player lists -----------------------------------------------------
    def _list(self, srv: _Server, list_id: str) -> tuple[GameList, Path]:
        gl = next((x for x in srv.game.lists if x.id == list_id), None)
        saves = srv.game.saves or GameSaves()
        base = srv.volumes.get(saves.volume)
        if gl is None or base is None:
            raise GameFeatureMissingError(f"no player list {list_id!r}", list=list_id)
        return gl, confined(base / gl.file, base.parent)

    async def lists(self, app_id: int) -> tuple[bool, list[PlayerList]]:
        srv = await self._server(app_id)
        values = await self._values(app_id)
        out = []
        for gl in srv.game.lists:
            _, path = self._list(srv, gl.id)
            out.append(PlayerList(
                id=gl.id, label=gl.label,
                editable=srv.container is not None or not gl.add,
                enabled=bool(values.get(gl.enabled_field)) if gl.enabled_field else None,
                name_pattern=gl.name_pattern,
                entries=await asyncio.to_thread(read_entries, path, gl),
            ))  # fmt: skip
        return srv.container is not None, out

    async def change_list(self, app_id: int, list_id: str, name: str, *, add: bool) -> str:
        srv = await self._server(app_id)
        gl, path = self._list(srv, list_id)
        if not re.fullmatch(gl.name_pattern, name):
            raise ValidationError("invalid player name", field="name")
        cmd = gl.add if add else gl.remove
        if cmd:
            out = await self._run(srv, [name if a == "{name}" else a for a in cmd])
        else:
            await asyncio.to_thread(edit_lines, path, name, add=add)
            out = ""
        self.bus.publish("game.list_added" if add else "game.list_removed",
                            app=srv.slug, target=name, list=list_id)  # fmt: skip
        return out

    async def set_list_enabled(self, app_id: int, list_id: str, enabled: bool) -> Job:
        srv = await self._server(app_id)
        gl, _ = self._list(srv, list_id)
        if not gl.enabled_field:
            raise GameFeatureMissingError(f"list {list_id!r} cannot be turned off")
        values = await self._values(app_id)
        return await self.apps.revisions.update(app_id, {**values, gl.enabled_field: enabled})

    # --- worlds -----------------------------------------------------------
    async def _saves(self, app_id: int) -> tuple[_Server, GameSaves, Path, str]:
        srv = await self._server(app_id)
        saves = srv.game.saves
        base = srv.volumes.get(saves.volume) if saves else None
        if saves is None or base is None:
            raise GameFeatureMissingError("this game has no worlds to manage")
        data = confined(base / saves.path, base.parent) if saves.path else base
        values = await self._values(app_id)
        active = str(values.get(saves.active_field) or "") if saves.active_field else ""
        return srv, saves, data, active

    async def worlds(self, app_id: int) -> tuple[str, list[w.World]]:
        _, saves, data, active = await self._saves(app_id)
        return active, await asyncio.to_thread(w.list_worlds, data, active, saves)

    async def _enqueue(self, app_id: int, slug: str, kind: JobKind, **params: Any) -> Job:
        async with self.sessions() as session, session.begin():
            job = self.jobs.add(session, kind, app_id=app_id, app_slug=slug, params=params)
        self.jobs.wake()
        return job

    async def import_world(
        self, app_id: int, name: str, filename: str, body: AsyncIterator[bytes]
    ) -> Job:
        srv, saves, data, _ = await self._saves(app_id)
        if saves.by_file:
            raise GameFeatureMissingError("this game's worlds cannot be imported as a folder")
        if (data / w.valid_world_name(name)).exists():
            raise w.WorldExistsError(f"a world named {name!r} already exists", name=name)
        # Next to the data volume (same filesystem, not visible to the server).
        upload = self.apps.volumes_dir(srv.slug) / f".hivora-upload-{secrets.token_hex(8)}.zip"
        await w.receive_upload(body, upload)
        return await self._enqueue(
            app_id, srv.slug, JobKind.WORLD_IMPORT, name=name, data=str(data),
            upload=str(upload), filename=filename[:100], marker=saves.marker,
        )  # fmt: skip

    async def activate_world(self, app_id: int, name: str) -> Job:
        _, saves, data, active = await self._saves(app_id)
        if not saves.active_field:
            raise GameFeatureMissingError("this game has no active world setting")
        w.existing_world(data, name, saves)
        if name == active:
            raise w.ActiveWorldError("this world is already active", name=name)
        values = await self._values(app_id)
        return await self.apps.revisions.update(app_id, {**values, saves.active_field: name})

    async def delete_world(self, app_id: int, name: str) -> Job:
        srv, saves, data, active = await self._saves(app_id)
        w.existing_world(data, name, saves)
        if name == active:
            raise w.ActiveWorldError("the active world cannot be deleted", name=name)
        return await self._enqueue(app_id, srv.slug, JobKind.WORLD_DELETE, name=name,
                                   data=str(data), layout=saves.model_dump())  # fmt: skip

    async def download_world(self, app_id: int, name: str) -> AsyncIterator[bytes]:
        srv, saves, data, active = await self._saves(app_id)
        w.existing_world(data, name, saves)
        if srv.container is not None and name == active and saves.flush:
            await self._run(srv, saves.flush)  # consistent files on disk
        self.bus.publish("game.world_downloaded", app=srv.slug, target=name)
        return w.zip_stream(w.world_paths(data, name, saves), data)
