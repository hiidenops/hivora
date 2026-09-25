"""Filesystem operations on app directories, confined to their roots."""

import fnmatch
import os
import shutil
from pathlib import Path

from hivora.core.errors import PermissionDeniedError


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
