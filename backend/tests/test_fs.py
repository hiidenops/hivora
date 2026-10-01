"""The shared file utilities, pinned before they move into hivora.core.fs."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hivora.core import fs
from hivora.core.errors import PermissionDeniedError
from hivora.games import worlds as w


def test_confined_keeps_paths_inside_their_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    assert fs.confined(root / "a" / "b", root) == (root / "a" / "b").resolve()
    assert fs.confined(root / "a" / ".." / "a", root) == (root / "a").resolve()
    assert fs.confined(root / "not-yet", root) == (root / "not-yet").resolve()
    for bad in (root, root / "..", root / "a" / ".." / ".." / "x", tmp_path / "elsewhere"):
        with pytest.raises(PermissionDeniedError):
            fs.confined(bad, root)
    (tmp_path / "outside").mkdir()
    (root / "link").symlink_to(tmp_path / "outside")  # a link inside, pointing out
    with pytest.raises(PermissionDeniedError):
        fs.confined(root / "link", root)
    with pytest.raises(PermissionDeniedError):
        fs.confined(root / "link" / "file", root)


def test_ensure_dir_creates_once_inside_its_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    uid, gid = 4321, 8765
    assert fs.ensure_dir(root / "app" / "data", root, uid=uid, gid=gid) is True
    assert (root / "app" / "data").is_dir()
    assert fs.ensure_dir(root / "app" / "data", root, uid=uid, gid=gid) is False
    if os.geteuid() == 0:  # ownership is only changed as root
        for p in (root / "app" / "data", root / "app"):
            assert (p.stat().st_uid, p.stat().st_gid) == (uid, gid)
        assert root.stat().st_uid != uid  # the root itself is left alone
    with pytest.raises(PermissionDeniedError):
        fs.ensure_dir(tmp_path / "elsewhere", root, uid=uid, gid=gid)
    assert not (tmp_path / "elsewhere").exists()


def test_remove_tree_inside_its_root_only(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "app" / "sub").mkdir(parents=True)
    (root / "app" / "sub" / "f").write_text("x")
    assert fs.remove_tree(root / "app", root) is True
    assert not (root / "app").exists()
    assert fs.remove_tree(root / "app", root) is False  # already gone
    (tmp_path / "keep").mkdir()
    with pytest.raises(PermissionDeniedError):
        fs.remove_tree(tmp_path / "keep", root)
    assert (tmp_path / "keep").is_dir()


def test_tree_size_counts_files_without_following_links(tmp_path: Path) -> None:
    (tmp_path / "d" / "e").mkdir(parents=True)
    (tmp_path / "d" / "a").write_bytes(b"x" * 10)
    (tmp_path / "d" / "e" / "b").write_bytes(b"y" * 32)
    big = tmp_path / "big"
    big.write_bytes(b"z" * 5000)
    (tmp_path / "d" / "link").symlink_to(big)  # counted as the link itself, not 5000
    size = fs.tree_size(tmp_path / "d")
    assert size == 10 + 32 + os.lstat(tmp_path / "d" / "link").st_size
    assert size < 5000
    assert fs.tree_size(tmp_path / "missing") == 0


def test_empty_dir_keeps_patterns_and_never_follows_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    data = root / "data"
    (data / "world").mkdir(parents=True)
    (data / "world" / "level.dat").write_text("w")
    (data / "server.properties").write_text("p")
    (data / "ops.json").write_text("[]")
    (data / "logs").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("keep me")
    (data / "escape").symlink_to(outside)

    removed = fs.empty_dir(data, root, keep=["*.json", "server.*"])
    assert removed == ["escape", "logs", "world"]  # sorted names
    assert sorted(p.name for p in data.iterdir()) == ["ops.json", "server.properties"]
    assert (outside / "precious").read_text() == "keep me"  # the link was unlinked only
    assert fs.empty_dir(root / "missing", root, keep=[]) == []
    (root / "file").write_text("x")
    assert fs.empty_dir(root / "file", root, keep=[]) == []
    with pytest.raises(PermissionDeniedError):
        fs.empty_dir(outside, root, keep=[])


async def test_receive_upload_refuses_an_empty_body(tmp_path: Path) -> None:
    async def nothing() -> AsyncIterator[bytes]:
        return
        yield b""  # an async generator that yields nothing

    with pytest.raises(w.InvalidArchiveError) as err:
        await w.receive_upload(nothing(), tmp_path / "empty.zip")
    assert err.value.code == "invalid_archive"
    assert not (tmp_path / "empty.zip").exists()
    assert w.ArchiveTooLargeError.code == "archive_too_large"
