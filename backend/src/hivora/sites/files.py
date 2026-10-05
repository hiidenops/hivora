"""A site's text files (.html, .css, .js): list, read, and replace one atomically.

Pure functions on the site's ``html`` folder, which is also their root: a path never
leaves it, and no symbolic link is followed or accepted on the way. A new content is
first staged in a work file next to ``html`` (same filesystem, never served), then moved
into place by a single ``os.replace``: nginx sees the old file or the new one, never a
mix. No content is ever logged.

``SiteFiles`` serves them: reads directly, writes through the ``site_file`` job, in the
app's lane.
"""

import asyncio
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.archive import DEFAULT_LIMITS
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from hivora.core.events import EventBus
from hivora.core.fs import confined, ensure_dir
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.sites import core

EDITABLE = (".html", ".css", ".js")
MAX_FILE = 1024**2  # bytes, read or written
MAX_LISTED = 5000


class InvalidPathError(ValidationError):
    code = "invalid_path"


class FileNotEditableError(ValidationError):
    code = "file_not_editable"


class NotTextError(ValidationError):
    code = "not_text"


class FileTooLargeError(ValidationError):
    code = "file_too_large"


class FileChangedError(ConflictError):
    code = "file_changed"


class SiteFileNotFoundError(NotFoundError):
    code = "site_file_not_found"


@dataclass(frozen=True, slots=True)
class SiteFile:
    path: str
    size: int
    modified: float  # POSIX timestamp


@dataclass(frozen=True, slots=True)
class TextFile:
    path: str
    content: str
    sha256: str
    size: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def editable(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in EDITABLE


def check_path(rel: str) -> PurePosixPath:
    """A relative POSIX path to an editable file, with the archives' size rules."""
    limits = DEFAULT_LIMITS
    if not rel or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        raise InvalidPathError("invalid path", path=rel[:200])
    parts = rel.split("/")
    if (
        any(p in ("", ".", "..") for p in parts)
        or len(parts) > limits.depth
        or len(rel.encode()) > limits.path
        or any(len(p.encode()) > limits.name for p in parts)
    ):
        raise InvalidPathError("invalid path", path=rel[:200])
    if not editable(parts[-1]):
        raise FileNotEditableError("only .html, .css and .js files can be edited", path=rel)
    return PurePosixPath(rel)


def resolve(html_dir: Path, rel: str) -> Path:
    """The file's absolute path; refused if any existing part of it is a symbolic link."""
    path = check_path(rel)
    current = html_dir
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise PermissionDeniedError("symbolic link in the path", path=rel)
    return confined(html_dir / path, html_dir)


def list_files(html_dir: Path, limit: int = MAX_LISTED) -> tuple[list[SiteFile], bool]:
    """Editable regular files, sorted by path; True if the list was cut at ``limit``."""
    found: list[SiteFile] = []
    for dirpath, _, names in os.walk(html_dir):  # links to folders are not followed
        for name in names:
            if not editable(name):
                continue
            path = Path(dirpath, name)
            st = path.lstat()
            if stat.S_ISREG(st.st_mode):  # links and special files left out
                rel = path.relative_to(html_dir).as_posix()
                found.append(SiteFile(rel, st.st_size, st.st_mtime))
    found.sort(key=lambda f: f.path)
    return found[:limit], len(found) > limit


def _read_bytes(target: Path, rel: str, max_size: int) -> bytes:
    try:
        st = target.lstat()
    except FileNotFoundError:
        raise SiteFileNotFoundError("no such file", path=rel) from None
    if not stat.S_ISREG(st.st_mode):
        raise FileNotEditableError("not a regular file", path=rel)
    if st.st_size > max_size:
        raise FileTooLargeError("file too large", path=rel, limit=max_size)
    # ponytail: O_NOFOLLOW guards the file itself; a folder swapped for a link between
    # the check and the open is not caught. Open each folder with openat if it matters.
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        data = f.read(max_size + 1)
    if len(data) > max_size:
        raise FileTooLargeError("file too large", path=rel, limit=max_size)
    return data


def read_file(html_dir: Path, rel: str, max_size: int = MAX_FILE) -> TextFile:
    data = _read_bytes(resolve(html_dir, rel), rel, max_size)
    if b"\x00" in data:
        raise NotTextError("not a text file", path=rel)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise NotTextError("not UTF-8 text", path=rel) from None
    return TextFile(rel, content, sha256(data), len(data))


def check_base(html_dir: Path, rel: str, base_sha256: str | None) -> Path:
    """The target, if it is still what the editor read (``None``: it must not exist)."""
    target = resolve(html_dir, rel)
    if base_sha256 is None:
        if os.path.lexists(target):
            raise FileChangedError("the file already exists", path=rel)
        return target
    if sha256(_read_bytes(target, rel, MAX_FILE)) != base_sha256:
        raise FileChangedError("the file was changed since it was read", path=rel)
    return target


def stage_edit(
    html_dir: Path, rel: str, content: str, base_sha256: str | None, edit: Path,
    *, uid: int, gid: int, max_size: int = MAX_FILE,
) -> int:  # fmt: skip
    """Check the edit, then write its content to ``edit`` (created here). Returns bytes."""
    if "\x00" in content:
        raise NotTextError("not a text file", path=rel)
    data = content.encode("utf-8")
    if len(data) > max_size:
        raise FileTooLargeError("file too large", path=rel, limit=max_size)
    check_base(html_dir, rel, base_sha256)
    fd = os.open(edit, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(edit, 0o644)
        if os.geteuid() == 0:
            os.chown(edit, uid, gid)
    except BaseException:
        edit.unlink(missing_ok=True)
        raise
    return len(data)


def apply_edit(
    html_dir: Path, rel: str, edit: Path, base_sha256: str | None, *, uid: int, gid: int
) -> bool:
    """Move a staged edit into place, if the file is still the one read. True if created.

    The staged file is always gone afterwards: moved, or removed on any error (the
    site's file is then left as it was).
    """
    try:
        target = check_base(html_dir, rel, base_sha256)
        current = html_dir
        for part in PurePosixPath(rel).parts[:-1]:  # parents of a new file
            current = current / part
            if not current.exists():
                current.mkdir()
                os.chmod(current, 0o755)  # noqa: S103 - a web folder: nginx reads it
                if os.geteuid() == 0:
                    os.chown(current, uid, gid)
            elif not current.is_dir():
                raise InvalidPathError("a parent of the path is a file", path=rel)
        os.replace(edit, target)
        dirfd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        edit.unlink(missing_ok=True)
    return base_sha256 is None


class SiteFiles:
    """A site's text files: listed and read at once, saved by the ``site_file`` job."""

    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue,
        settings: Settings, bus: EventBus,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.jobs = jobs
        self.settings = settings
        self.bus = bus

    def register(self) -> None:
        self.jobs.register(JobKind.SITE_FILE, self.save_job)

    async def _folder(self, app_id: int, site_id: int | None) -> Path:
        async with self.sessions() as session:
            app = await core.get_site(session, app_id)
            folder, _ = await core.site_root(session, app.id, site_id)
            return folder

    async def list(self, app_id: int, site_id: int | None = None) -> tuple[list[SiteFile], bool]:
        """``site_id``: one of the app's sites (None: its main site), each its own root."""
        return await asyncio.to_thread(list_files, await self._folder(app_id, site_id))

    async def read(self, app_id: int, rel: str, site_id: int | None = None) -> TextFile:
        return await asyncio.to_thread(read_file, await self._folder(app_id, site_id), rel)

    async def save(self, app_id: int, rel: str, content: str, base_sha256: str | None,
                   site_id: int | None = None) -> Job:  # fmt: skip
        """Check and stage the new content next to the site, then queue its move.

        Refused here (nothing queued) if the path, the content or the base is wrong; the
        job checks the base again before moving the file into place.
        """
        app, folder, app_dir = await core.deployed_root(self.sessions, app_id, site_id)
        root, s = self.settings.volumes_root, self.settings
        await asyncio.to_thread(ensure_dir, app_dir, root, uid=s.puid, gid=s.pgid)
        edit = confined(app_dir / f".hivora-edit-{secrets.token_hex(8)}", root)
        try:
            size = await asyncio.to_thread(stage_edit, folder, rel, content, base_sha256,
                                           edit, uid=s.puid, gid=s.pgid)  # fmt: skip
            params: dict[str, object] = {"path": rel, "edit": str(edit),
                                         "base_sha256": base_sha256, "bytes": size}  # fmt: skip
            if site_id is not None:
                params["site_id"] = site_id
            async with self.sessions() as session, session.begin():
                job = self.jobs.add(session, JobKind.SITE_FILE, app_id=app.id,
                                    app_slug=app.slug, params=params)  # fmt: skip
        except BaseException:
            edit.unlink(missing_ok=True)
            raise
        self.jobs.wake()
        return job

    async def save_job(self, ctx: JobContext) -> None:
        """The site_file job: move a staged file into place, if the file is unchanged."""
        s, rel = self.settings, ctx.params["path"]
        site_id = ctx.params.get("site_id")  # absent: the main site (jobs queued before)
        edit = confined(Path(ctx.params["edit"]), s.volumes_root)
        try:
            app, folder, app_dir = await core.deployed_root(self.sessions, ctx.app_id or 0, site_id)
            await asyncio.to_thread(core.sweep, app_dir, edit)
            # An added site's first file: its folder (the main site's always exists).
            await asyncio.to_thread(ensure_dir, folder, s.volumes_root, uid=s.puid, gid=s.pgid)
            base = ctx.params["base_sha256"]
            created = await asyncio.to_thread(apply_edit, folder, rel, edit, base,
                                              uid=s.puid, gid=s.pgid)  # fmt: skip
        finally:
            edit.unlink(missing_ok=True)
        size = ctx.params.get("bytes", 0)
        await ctx.log(f"{'created' if created else 'saved'} {rel} ({size} bytes)")
        extra = {"site_id": site_id} if site_id is not None else {}
        self.bus.publish("site.file_saved", app=app.slug, path=rel, bytes=size, created=created,
                         **extra)  # fmt: skip
