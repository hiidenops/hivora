import io
import os
import stat
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hivora.core.errors import ValidationError
from hivora.games import worlds as w


def make_zip(path: Path, members: dict[str, bytes], symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return path


def extract(archive: Path, data: Path, name: str = "imported") -> Path:
    w.extract_world(archive, data / name, uid=os.getuid(), gid=os.getgid())
    return data / name


def test_extract_finds_the_world_inside_a_folder(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    archive = make_zip(tmp_path / "a.zip", {
        "My World/level.dat": b"L", "My World/region/r.0.0.mca": b"R" * 100, "readme.txt": b"x",
    })  # fmt: skip
    world = extract(archive, data)
    assert (world / "level.dat").read_bytes() == b"L"
    assert (world / "region" / "r.0.0.mca").stat().st_size == 100
    assert not (world / "readme.txt").exists()  # outside the world's folder
    assert [p.name for p in data.iterdir()] == ["imported"]  # staging renamed away
    with pytest.raises(w.WorldExistsError):
        extract(archive, data)


@pytest.mark.parametrize(
    ("members", "symlink"),
    [
        ({"level.dat": b"L", "../evil": b"x"}, None),
        ({"level.dat": b"L", "/etc/evil": b"x"}, None),
        ({"level.dat": b"L", "a\\..\\evil": b"x"}, None),
        ({"level.dat": b"L"}, "link"),
        ({"region/r.mca": b"x"}, None),  # no level.dat
    ],
)
def test_unsafe_or_invalid_archives_are_refused(
    tmp_path: Path, members: dict[str, bytes], symlink: str | None
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(w.InvalidArchiveError):
        extract(make_zip(tmp_path / "a.zip", members, symlink), data)
    assert list(data.iterdir()) == [] and not (tmp_path / "evil").exists()


def test_size_caps_and_garbage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(w, "MAX_EXTRACTED", 1000)
    with pytest.raises(w.ArchiveTooLargeError):  # a zip bomb in miniature
        extract(make_zip(tmp_path / "a.zip", {"level.dat": b"\0" * 5000}), data)
    (tmp_path / "junk.zip").write_bytes(b"not a zip")
    with pytest.raises(w.InvalidArchiveError):
        extract(tmp_path / "junk.zip", data)
    assert list(data.iterdir()) == []


def test_list_groups_dimensions_and_marks_active(tmp_path: Path) -> None:
    for d in ("world", "world_nether", "world_the_end", "creative", ".hivora-import-x"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "level.dat").write_bytes(b"12345")
    (tmp_path / "logs").mkdir()
    found = w.list_worlds(tmp_path, "world")
    assert [(x.name, x.size, x.active) for x in found] == [
        ("world", 15, True), ("creative", 5, False),
    ]  # fmt: skip
    assert w.delete_world(tmp_path, "world", tmp_path) == ["world", "world_nether", "world_the_end"]
    with pytest.raises(w.WorldNotFoundError):
        w.existing_world(tmp_path, "logs")
    with pytest.raises(ValidationError):
        w.existing_world(tmp_path, "../etc")


async def test_zip_stream_round_trip(tmp_path: Path) -> None:
    (tmp_path / "world" / "region").mkdir(parents=True)
    (tmp_path / "world" / "level.dat").write_bytes(b"L")
    (tmp_path / "world" / "session.lock").write_bytes(b"")
    (tmp_path / "world" / "region" / "r.mca").write_bytes(os.urandom(300_000))
    body = b"".join([c async for c in w.zip_stream([tmp_path / "world"], tmp_path)])
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert sorted(zf.namelist()) == ["world/level.dat", "world/region/r.mca"]
        assert zf.testzip() is None
    # Re-importable as is.
    (tmp_path / "back.zip").write_bytes(body)
    (tmp_path / "data").mkdir()
    assert (extract(tmp_path / "back.zip", tmp_path / "data") / "level.dat").exists()


async def test_upload_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(n: int) -> AsyncIterator[bytes]:
        for _ in range(n):
            yield b"x" * 100

    monkeypatch.setattr(w, "MAX_UPLOAD", 250)
    assert await w.receive_upload(body(2), tmp_path / "ok.zip") == 200
    with pytest.raises(w.ArchiveTooLargeError):
        await w.receive_upload(body(3), tmp_path / "big.zip")
    assert not (tmp_path / "big.zip").exists()
