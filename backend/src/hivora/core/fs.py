"""Filesystem operations shared by the modules: paths confined to their roots, app
directories, streamed uploads of archives (sizes capped), and a folder's contents
replaced in place."""

import asyncio
import fnmatch
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from hivora.core.errors import ConflictError, PermissionDeniedError, ValidationError

UPLOAD_LIMIT = 10 * 1024**3  # an uploaded archive, as sent


class InvalidArchiveError(ValidationError):
    code = "invalid_archive"


class ArchiveTooLargeError(ValidationError):
    code = "archive_too_large"


class NotEnoughSpaceError(ConflictError):
    code = "not_enough_space"


def confined(path: Path, root: Path) -> Path:
    """Resolve ``path`` and refuse anything outside ``root`` (or ``root`` itself)."""
    resolved, base = path.resolve(), root.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise PermissionDeniedError("path outside of its root", path=str(path))
    return resolved


def ensure_dir(path: Path, root: Path, *, uid: int, gid: int) -> bool:
    """Create a bind-mount directory owned by the app user. True if created."""
    target = confined(path, root)
    if target.exists():
        return False
    target.mkdir(parents=True)
    if os.geteuid() == 0:
        # Chown the whole chain created below root so the app can write.
        for p in (target, *target.parents):
            if p == root.resolve():
                break
            os.chown(p, uid, gid)
    return True


def remove_tree(path: Path, root: Path) -> bool:
    target = confined(path, root)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def tree_size(path: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def empty_dir(path: Path, root: Path, keep: list[str]) -> list[str]:
    """Delete everything in ``path`` except top-level entries matching ``keep``.

    Returns the removed entry names. Symlinks are unlinked, never followed.
    """
    target = confined(path, root)
    if not target.is_dir():
        return []
    removed = []
    for entry in sorted(target.iterdir()):
        if any(fnmatch.fnmatch(entry.name, k) for k in keep):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed.append(entry.name)
    return removed


async def receive_upload(chunks: AsyncIterator[bytes], dest: Path,
                         limit: int = UPLOAD_LIMIT) -> int:  # fmt: skip
    """Write a streamed request body to `dest`, capped at `limit`."""
    size = 0
    try:
        with dest.open("wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise ArchiveTooLargeError("archive too large", limit=limit)
                # ponytail: blocking writes of small chunks; move to a thread if it shows.
                out.write(chunk)
    except BaseException:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise
    if size == 0:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise InvalidArchiveError("empty upload")
    return size


def replace_contents(target: Path, staging: Path, root: Path) -> list[str]:
    """Swap the entries of ``target`` for those of ``staging``; returns the new names.

    ``target`` itself is kept (same inode): it can be a bind-mount source, which a
    running container keeps even if the folder is renamed. Only renames on one
    filesystem: the old entries go to ``<staging>.old`` first, then the new ones move
    in. On any error, every move is undone, in reverse order, before raising.
    ponytail: in between, the folder is mixed or partly empty for 2N renames (N
    top-level entries, well under a millisecond); swap a symlink if that matters.
    """
    target, staging = confined(target, root), confined(staging, root)
    old = confined(staging.with_name(f"{staging.name}.old"), root)
    old.mkdir()
    moved_out: list[str] = []
    moved_in: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            os.rename(entry, old / entry.name)
            moved_out.append(entry.name)
        for entry in sorted(staging.iterdir()):
            os.rename(entry, target / entry.name)
            moved_in.append(entry.name)
    except BaseException:
        for name in reversed(moved_in):
            os.rename(target / name, staging / name)
        for name in reversed(moved_out):
            os.rename(old / name, target / name)
        old.rmdir()
        raise
    shutil.rmtree(old)
    staging.rmdir()
    return moved_in
