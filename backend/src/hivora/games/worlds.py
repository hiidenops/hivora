"""Game worlds/saves on a server's volume: list, import, download, delete.

The template's `game.saves` describes them: folders holding a marker file
(Minecraft: `level.dat`, plus sibling dimension folders), or files grouped by
name (`*.fwl`: `<name>.fwl`, `<name>.db`...). Hivora reaches it through the bind
mount (same path as on the host), never through Docker. Imports are untrusted
archives: every member is checked (no absolute path, no `..`, no symlink),
sizes are capped and the world lands in place with one rename.
"""

import asyncio
import os
import queue
import re
import shutil
import stat
import threading
import zipfile
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from hivora.core import fs
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.fs import (  # re-exported: games and tests use them from here
    ArchiveTooLargeError as ArchiveTooLargeError,
)
from hivora.core.fs import (
    InvalidArchiveError as InvalidArchiveError,
)
from hivora.core.fs import (
    NotEnoughSpaceError as NotEnoughSpaceError,
)
from hivora.core.fs import confined, remove_tree, tree_size
from hivora.jobs import JobContext, JobKind
from hivora.templates.schema import GameSaves

if TYPE_CHECKING:
    from hivora.apps.service import AppService

WORLD_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,47}$")  # Factorio: _autosave1
MAX_UPLOAD = 10 * 1024**3  # the .zip as sent
MAX_EXTRACTED = 30 * 1024**3  # its content: stops zip bombs
MAX_MEMBERS = 500_000
FREE_MARGIN = 512 * 1024**2  # never fill the disk to the last byte
# Paper/Spigot keep the other dimensions in sibling folders: world_nether, world_the_end.
DIMENSIONS = ("_nether", "_the_end")
MINECRAFT = GameSaves(marker="level.dat", siblings=list(DIMENSIONS))


class WorldNotFoundError(NotFoundError):
    code = "world_not_found"


class WorldExistsError(ConflictError):
    code = "world_exists"


class ActiveWorldError(ConflictError):
    code = "world_active"


@dataclass(frozen=True, slots=True)
class World:
    name: str
    size: int  # bytes, dimension folders included
    modified: float  # level.dat mtime
    active: bool


def valid_world_name(name: str) -> str:
    if not WORLD_NAME.match(name):
        raise ValidationError("invalid world name", field="name")
    return name


def world_paths(data: Path, name: str, layout: GameSaves = MINECRAFT) -> list[Path]:
    """Everything that belongs to the world: its folder(s) or its files."""
    if layout.by_file:
        return sorted(p for p in data.glob(f"{name}.*") if p.is_file() and not p.is_symlink())
    candidates = (data / name, *(data / f"{name}{s}" for s in layout.siblings))
    return [p for p in candidates if p.is_dir()]


def _marker(data: Path, name: str, layout: GameSaves) -> Path:
    return data / f"{name}{layout.marker[1:]}" if layout.by_file else data / name / layout.marker


def list_worlds(data: Path, active: str, layout: GameSaves = MINECRAFT) -> list[World]:
    if not data.is_dir():
        return []
    if layout.by_file:
        names = {p.name.removesuffix(layout.marker[1:]) for p in data.glob(layout.marker)
                 if p.is_file() and not p.is_symlink()}  # fmt: skip
    else:
        names = {
            p.name
            for p in data.iterdir()
            if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
            and (p / layout.marker).is_file()
        }  # fmt: skip
    worlds = [
        World(
            name=name,
            size=sum(
                p.stat().st_size if p.is_file() else tree_size(p)
                for p in world_paths(data, name, layout)
            ),
            modified=_marker(data, name, layout).stat().st_mtime,
            active=name == active,
        )
        for name in names
        if WORLD_NAME.match(name)
        and not any(name.endswith(s) and name[: -len(s)] in names for s in layout.siblings)
    ]
    return sorted(worlds, key=lambda w: (not w.active, w.name.lower()))


def existing_world(data: Path, name: str, layout: GameSaves = MINECRAFT) -> Path:
    marker = _marker(data, valid_world_name(name), layout)
    if not marker.is_file():
        raise WorldNotFoundError(f"no world named {name!r}", name=name)
    return data / name


def delete_world(data: Path, name: str, root: Path, layout: GameSaves = MINECRAFT) -> list[str]:
    existing_world(data, name, layout)
    removed = []
    for path in world_paths(data, name, layout):
        if path.is_dir():
            remove_tree(path, root)
        else:
            confined(path, root).unlink()
        removed.append(path.name)
    return removed


def _members(
    zf: zipfile.ZipFile, marker: str
) -> tuple[str, list[tuple[zipfile.ZipInfo, PurePosixPath]], int]:
    """Validate an archive; return the world's root prefix, its members and their size."""
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ArchiveTooLargeError("too many files in the archive", limit=MAX_MEMBERS)
    roots = [
        i.filename.removesuffix(marker)
        for i in infos
        if not i.is_dir() and PurePosixPath(i.filename).name == marker
    ]
    if not roots:
        raise InvalidArchiveError(f"no {marker} in the archive: not a world", marker=marker)
    # ponytail: the shallowest marker wins; Paper dimension folders zipped
    # next to it are skipped. Import them as their own world if needed.
    root = min(roots, key=len)
    members, total = [], 0
    for info in infos:
        name = info.filename
        if "\\" in name or name.startswith("/") or ".." in PurePosixPath(name).parts:
            raise InvalidArchiveError("unsafe path in the archive", member=name[:200])
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidArchiveError("symbolic link in the archive", member=name[:200])
        if not name.startswith(root) or name == root:
            continue
        total += info.file_size
        members.append((info, PurePosixPath(name[len(root) :])))
    if total > MAX_EXTRACTED:
        raise ArchiveTooLargeError("world too large once extracted", limit=MAX_EXTRACTED)
    return root, members, total


def extract_world(
    archive: Path, target: Path, *, uid: int, gid: int,
    progress: Callable[[int], None] = lambda _: None, marker: str = "level.dat",
) -> int:  # fmt: skip
    """Extract a world archive to `target` (which must not exist). Returns bytes written.

    Blocking: run it in a thread. Extracts to a hidden sibling folder first,
    then renames, so a failed import never leaves a half world behind.
    """
    if target.exists():
        raise WorldExistsError(f"a world named {target.name!r} already exists", name=target.name)
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidArchiveError(f"not a valid .zip file: {exc}") from exc
    with zf:
        _, members, total = _members(zf, marker)
        free = shutil.disk_usage(target.parent).free
        if free < total + FREE_MARGIN:
            raise NotEnoughSpaceError("not enough disk space", needed=total, free=free)
        staging = target.parent / f".hivora-import-{target.name}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        try:
            written, step = 0, 0
            for info, rel in members:
                dest = staging.joinpath(*rel.parts)
                if not dest.resolve().is_relative_to(staging.resolve()):
                    raise InvalidArchiveError("unsafe path in the archive", member=str(rel))
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                # zipfile stops at the declared size and checks the CRC.
                with zf.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                written += info.file_size
                if total and (pct := written * 100 // total) >= step + 2:
                    step = pct
                    progress(pct)
            if os.geteuid() == 0:
                for dirpath, dirs, files in os.walk(staging):
                    for n in (dirpath, *(os.path.join(dirpath, x) for x in (*dirs, *files))):
                        os.chown(n, uid, gid)
            staging.rename(target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return written


async def receive_upload(chunks: AsyncIterator[bytes], dest: Path) -> int:
    """Write a streamed request body to `dest`, capped at MAX_UPLOAD (read at call time)."""
    return await fs.receive_upload(chunks, dest, limit=MAX_UPLOAD)


async def zip_stream(paths: list[Path], base: Path) -> AsyncIterator[bytes]:
    """Stream a .zip of `paths` (names relative to `base`) without a temp file."""
    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
    stop = threading.Event()

    def put(item: bytes | None) -> None:
        while not stop.is_set():
            try:
                chunks.put(item, timeout=0.5)
                return
            except queue.Full:
                pass
        raise OSError("download cancelled")

    class Sink:  # write-only, unseekable: zipfile then writes data descriptors
        def write(self, data: bytes) -> int:
            put(bytes(data))
            return len(data)

        def flush(self) -> None:
            pass

    def produce() -> None:
        try:
            # Region files are already compressed: favour speed.
            with zipfile.ZipFile(Sink(), "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:  # type: ignore[call-overload]
                for top in paths:
                    # A folder world is walked; a file world is its own single entry.
                    walked: Iterable[tuple[str, list[str], list[str]]] = (
                        os.walk(top) if top.is_dir() else [(str(top.parent), [], [top.name])]
                    )
                    for dirpath, _, files in walked:
                        for f in sorted(files):
                            path = Path(dirpath, f)
                            if path.is_symlink() or f == "session.lock":
                                continue
                            try:
                                zf.write(path, path.relative_to(base).as_posix())
                            except FileNotFoundError:
                                continue  # removed by the running server meanwhile
        finally:
            try:
                put(None)
            except OSError:
                pass

    task = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while (chunk := await asyncio.to_thread(chunks.get)) is not None:
            yield chunk
    finally:
        stop.set()
        while not chunks.empty():
            chunks.get_nowait()
        try:
            await task
        except OSError:
            pass


class WorldJobs:
    """Job handlers: world imports and deletions run in the app's job lane."""

    def __init__(self, apps: "AppService") -> None:
        self.apps = apps

    def register(self) -> None:
        self.apps.jobs.register(JobKind.WORLD_IMPORT, self.import_world)
        self.apps.jobs.register(JobKind.WORLD_DELETE, self.delete_world)

    async def import_world(self, ctx: JobContext) -> None:
        s = self.apps.settings
        data = confined(Path(ctx.params["data"]), s.volumes_root)
        upload = confined(Path(ctx.params["upload"]), s.volumes_root)
        name = valid_world_name(ctx.params["name"])
        loop = asyncio.get_running_loop()

        def progress(pct: int) -> None:
            asyncio.run_coroutine_threadsafe(ctx.progress(pct, "Extracting the world"), loop)

        try:
            await ctx.log(
                f"extracting {ctx.params.get('filename') or upload.name} into {data / name}"
            )
            written = await asyncio.to_thread(
                extract_world,
                upload,
                data / name,
                uid=s.puid,
                gid=s.pgid,
                progress=progress,
                marker=ctx.params.get("marker", "level.dat"),
            )
        finally:
            upload.unlink(missing_ok=True)
        await ctx.log(f"world {name} imported ({written} bytes)")
        self.apps.bus.publish("game.world_imported", app=ctx.app_slug, target=name)

    async def delete_world(self, ctx: JobContext) -> None:
        s = self.apps.settings
        data = confined(Path(ctx.params["data"]), s.volumes_root)
        name = ctx.params["name"]
        layout = GameSaves.model_validate(ctx.params.get("layout") or MINECRAFT.model_dump())
        removed = await asyncio.to_thread(delete_world, data, name, s.volumes_root, layout)
        await ctx.log(f"removed {', '.join(removed)}")
        self.apps.bus.publish("game.world_deleted", app=ctx.app_slug, target=name)
