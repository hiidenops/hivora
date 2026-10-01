"""Zip archives handled safely: check the central directory first (paths, member types,
sizes), then extract to a new staging folder. Generic: no business module imported.

Every name is checked before anything is written; sizes are checked as declared, then
again on the bytes actually written, since a declared size can lie.
"""

import os
import re
import shutil
import stat
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hivora.core.fs import ArchiveTooLargeError, InvalidArchiveError, NotEnoughSpaceError

IGNORED_DIRS = {"__MACOSX"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
_DRIVE = re.compile(r"^[A-Za-z]:")
_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Limits:
    members: int = 10_000
    total: int = 1024**3  # bytes once extracted
    ratio: int = 200  # uncompressed / compressed, beyond: a bomb...
    ratio_from: int = 1024**2  # ...for members larger than this
    depth: int = 32
    name: int = 255  # bytes per path component
    path: int = 1024  # bytes per full path
    free_margin: int = 512 * 1024**2  # never fill the disk to the last byte


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True, slots=True)
class Member:
    info: zipfile.ZipInfo
    path: PurePosixPath  # relative to the extracted root (single top folder removed)


@dataclass(frozen=True, slots=True)
class Plan:
    members: list[Member]  # files and folders, ignored entries left out
    prefix: str  # the single top folder removed, "" if none
    total: int  # declared bytes once extracted

    def files(self) -> list[str]:
        return [str(m.path) for m in self.members if not m.info.is_dir()]


def open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidArchiveError(f"not a valid .zip file: {exc}") from exc


def _parts(info: zipfile.ZipInfo, limits: Limits) -> tuple[str, ...]:
    name = info.filename
    if "\x00" in name or "\\" in name or name.startswith("/") or _DRIVE.match(name):
        raise InvalidArchiveError("unsafe path in the archive", member=name[:200])
    parts = tuple(name.removesuffix("/").split("/"))
    if any(p in ("", ".", "..") for p in parts):
        raise InvalidArchiveError("unsafe path in the archive", member=name[:200])
    if (
        len(parts) > limits.depth
        or len(name.encode()) > limits.path
        or any(len(p.encode()) > limits.name for p in parts)
    ):
        raise InvalidArchiveError("path too long in the archive", member=name[:200])
    kind = stat.S_IFMT(info.external_attr >> 16)
    if kind == stat.S_IFLNK:
        raise InvalidArchiveError("symbolic link in the archive", member=name[:200])
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise InvalidArchiveError("unsupported member type in the archive", member=name[:200])
    if info.flag_bits & 0x1:
        raise InvalidArchiveError("encrypted member in the archive", member=name[:200])
    return parts


def inspect(zf: zipfile.ZipFile, limits: Limits = DEFAULT_LIMITS) -> Plan:
    """Validate every member from the central directory; nothing is read or written."""
    infos = zf.infolist()
    if len(infos) > limits.members:
        raise ArchiveTooLargeError("too many files in the archive", limit=limits.members)
    kept: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    total = 0
    for info in infos:
        parts = _parts(info, limits)
        if parts in seen:
            raise InvalidArchiveError("duplicate name in the archive", member=info.filename[:200])
        seen.add(parts)
        if IGNORED_DIRS & set(parts) or parts[-1] in IGNORED_FILES:
            continue
        if not info.is_dir():
            total += info.file_size
            if total > limits.total:
                raise ArchiveTooLargeError("too large once extracted", limit=limits.total)
            if info.file_size > limits.ratio_from and info.file_size > limits.ratio * max(
                info.compress_size, 1
            ):
                raise ArchiveTooLargeError(
                    "suspicious compression ratio", member=info.filename[:200], limit=limits.ratio
                )
        kept.append((info, parts))
    files = [parts for info, parts in kept if not info.is_dir()]
    if not files:
        raise InvalidArchiveError("the archive is empty")
    folders = {parts[:i] for parts in files for i in range(1, len(parts))}
    if folders & set(files):  # "a" both a file and a folder
        clash = "/".join(min(folders & set(files)))
        raise InvalidArchiveError("duplicate name in the archive", member=clash[:200])
    tops = {parts[0] for parts in files}
    single = len(tops) == 1 and all(len(parts) > 1 for parts in files)
    strip = 1 if single else 0
    members = [
        Member(info, PurePosixPath(*parts[strip:])) for info, parts in kept if len(parts) > strip
    ]
    return Plan(members, f"{next(iter(tops))}/" if single else "", total)


def extract(
    zf: zipfile.ZipFile, plan: Plan, staging: Path, *, uid: int, gid: int,
    limits: Limits = DEFAULT_LIMITS, progress: Callable[[int], None] = lambda _: None,
) -> int:  # fmt: skip
    """Write the plan's members into ``staging`` (created here, must not exist).

    Blocking: run it in a thread. Files 0644, folders 0755 (the archive's modes are
    ignored), owned by ``uid:gid`` when running as root. Returns the bytes written; on
    any error ``staging`` is removed.
    """
    free = shutil.disk_usage(staging.parent).free
    if free < plan.total + limits.free_margin:
        raise NotEnoughSpaceError("not enough disk space", needed=plan.total, free=free)
    staging.mkdir()
    base = staging.resolve()
    written, step = 0, 0
    try:
        for member in plan.members:
            dest = base.joinpath(*member.path.parts)
            if not dest.resolve().is_relative_to(base):
                raise InvalidArchiveError("unsafe path in the archive", member=str(member.path))
            if member.info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with zf.open(member.info) as src, os.fdopen(fd, "wb") as out:
                while chunk := src.read(_CHUNK):
                    written += len(chunk)
                    if written > limits.total:
                        raise ArchiveTooLargeError("too large once extracted", limit=limits.total)
                    out.write(chunk)
            if plan.total and (pct := written * 100 // plan.total) >= step + 2:
                step = pct
                progress(min(pct, 100))
        for dirpath, _, names in os.walk(base):
            files = (os.path.join(dirpath, n) for n in names)
            for path, mode in ((dirpath, 0o755), *((f, 0o644) for f in files)):
                os.chmod(path, mode)
                if os.geteuid() == 0:
                    os.chown(path, uid, gid)
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InvalidArchiveError(f"corrupt archive: {exc}") from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return written
