"""core.archive (safe zip inspection and extraction) and core.fs.replace_contents."""

import os
import stat
import warnings
import zipfile
from pathlib import Path
from typing import Any

import pytest

from hivora.core import archive, fs
from hivora.core.errors import HivoraError, PermissionDeniedError

NO_MARGIN = archive.Limits(free_margin=0)
UID, GID = os.getuid(), os.getgid()


def make_zip(path: Path, *members: Any) -> Path:
    """Members: (name, data) or a ready ZipInfo with its data, (info, data)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names on purpose
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members:
                zf.writestr(name, data)
    return path


def link(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def refused(zf: zipfile.ZipFile, code: str, message: str = "") -> HivoraError:
    with pytest.raises(HivoraError) as err:
        archive.inspect(zf)
    assert err.value.code == code and message in str(err.value)
    return err.value


def extract(zf: zipfile.ZipFile, staging: Path, limits: archive.Limits = NO_MARGIN) -> int:
    return archive.extract(
        zf, archive.inspect(zf, limits), staging, limits=limits, uid=UID, gid=GID
    )


def test_a_sound_archive_is_extracted_with_safe_modes(tmp_path: Path) -> None:
    exe = zipfile.ZipInfo("bin/run.sh")
    exe.external_attr = (stat.S_IFREG | stat.S_ISUID | 0o777) << 16
    path = make_zip(tmp_path / "a.zip", ("index.html", "<h1>hi</h1>"), ("css/site.css", "a{}"),
                    ("img/", ""), (exe, "#!/bin/sh"))  # fmt: skip
    with archive.open_zip(path) as zf:
        plan = archive.inspect(zf)
        assert plan.prefix == "" and plan.total == 11 + 3 + 9
        assert sorted(plan.files()) == ["bin/run.sh", "css/site.css", "index.html"]
        assert archive.extract(zf, plan, tmp_path / "out", limits=NO_MARGIN, uid=UID, gid=GID) == 23
    out = tmp_path / "out"
    assert (out / "index.html").read_text() == "<h1>hi</h1>"
    assert (out / "img").is_dir()  # empty folders kept
    for p in (out / "index.html", out / "css" / "site.css", out / "bin" / "run.sh"):
        assert stat.S_IMODE(p.stat().st_mode) == 0o644  # no exec, no setuid
    for p in (out, out / "css", out / "img"):
        assert stat.S_IMODE(p.stat().st_mode) == 0o755


def test_a_single_top_folder_is_removed_once(tmp_path: Path) -> None:
    single = make_zip(tmp_path / "s.zip", ("site/", ""), ("site/index.html", "i"),
                      ("site/a/b.css", "b"), ("__MACOSX/site/._index.html", "x"),
                      ("site/.DS_Store", "x"), ("Thumbs.db", "x"))  # fmt: skip
    with archive.open_zip(single) as zf:
        plan = archive.inspect(zf)
        assert plan.prefix == "site/" and sorted(plan.files()) == ["a/b.css", "index.html"]
        extract(zf, tmp_path / "s")
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["a", "index.html"]

    nested = make_zip(tmp_path / "n.zip", ("a/b/index.html", "i"))  # one level only
    with archive.open_zip(nested) as zf:
        assert archive.inspect(zf).files() == ["b/index.html"]

    mixed = make_zip(tmp_path / "m.zip", ("index.html", "i"), ("site/x.css", "x"))
    with archive.open_zip(mixed) as zf:
        plan = archive.inspect(zf)
        assert plan.prefix == "" and sorted(plan.files()) == ["index.html", "site/x.css"]


@pytest.mark.parametrize(
    "name", ["/etc/passwd", "../evil", "a/../../evil", "a/./b", "C:evil", "a\\..\\evil", "a//b"]
)
def test_unsafe_paths_are_refused(tmp_path: Path, name: str) -> None:
    path = make_zip(tmp_path / "u.zip", ("index.html", "i"), (name, "x"))
    with archive.open_zip(path) as zf:
        err = refused(zf, "invalid_archive", "unsafe path")
        assert err.details == {"member": name}


def test_links_special_files_encryption_and_duplicates_are_refused(tmp_path: Path) -> None:
    with archive.open_zip(make_zip(tmp_path / "l.zip", (link("index.html"), "/etc"))) as zf:
        refused(zf, "invalid_archive", "symbolic link")

    fifo = zipfile.ZipInfo("pipe")
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
    with archive.open_zip(make_zip(tmp_path / "f.zip", (fifo, ""))) as zf:
        refused(zf, "invalid_archive", "unsupported member type")

    with archive.open_zip(make_zip(tmp_path / "e.zip", ("index.html", "i"))) as zf:
        zf.infolist()[0].flag_bits |= 0x1  # as an encrypted archive reads
        refused(zf, "invalid_archive", "encrypted")

    with archive.open_zip(make_zip(tmp_path / "d.zip", ("a.html", "1"), ("a.html", "2"))) as zf:
        refused(zf, "invalid_archive", "duplicate name")
    clash = make_zip(tmp_path / "c.zip", ("a", "file"), ("a/b.html", "under a file"))
    with archive.open_zip(clash) as zf:
        refused(zf, "invalid_archive", "duplicate name")


def test_empty_archives_and_non_zip_files_are_refused(tmp_path: Path) -> None:
    junk = make_zip(tmp_path / "j.zip", ("empty/", ""), ("__MACOSX/x", "x"), (".DS_Store", "x"))
    with archive.open_zip(junk) as zf:
        refused(zf, "invalid_archive", "empty")
    (tmp_path / "not.zip").write_bytes(b"PK? no")
    with pytest.raises(fs.InvalidArchiveError):
        archive.open_zip(tmp_path / "not.zip")


def test_zip_bombs_are_stopped(tmp_path: Path) -> None:
    small = archive.Limits(members=3, total=100, free_margin=0)
    many = make_zip(tmp_path / "m.zip", *((f"{i}.html", "x") for i in range(4)))
    with archive.open_zip(many) as zf, pytest.raises(fs.ArchiveTooLargeError, match="too many"):
        archive.inspect(zf, small)
    big = make_zip(tmp_path / "b.zip", ("a.html", "x" * 60), ("b.html", "x" * 60))
    with archive.open_zip(big) as zf, pytest.raises(fs.ArchiveTooLargeError, match="too large"):
        archive.inspect(zf, small)

    # Highly compressible: refused on its ratio before anything is written.
    zeros = make_zip(tmp_path / "z.zip", ("zeros.html", b"\0" * (2 * 1024**2)))
    with archive.open_zip(zeros) as zf:
        err = refused(zf, "archive_too_large", "compression ratio")
        assert err.details["limit"] == 200

    # A declared size that lies: zipfile stops at it and the CRC fails; nothing left.
    liar = make_zip(tmp_path / "liar.zip", ("index.html", "x" * 5000))
    with archive.open_zip(liar) as zf:
        zf.infolist()[0].file_size = 10
        with pytest.raises(fs.InvalidArchiveError, match="corrupt"):
            extract(zf, tmp_path / "liar")
    assert not (tmp_path / "liar").exists()

    # Bytes actually written are counted too, whatever the declared total says.
    with archive.open_zip(big) as zf:
        plan = archive.inspect(zf)
        with pytest.raises(fs.ArchiveTooLargeError):
            archive.extract(zf, plan, tmp_path / "count", limits=archive.Limits(total=100,
                            free_margin=0), uid=UID, gid=GID)  # fmt: skip
    assert not (tmp_path / "count").exists()


def test_extraction_needs_free_space_and_a_new_staging_folder(tmp_path: Path) -> None:
    path = make_zip(tmp_path / "a.zip", ("index.html", "i"))
    with archive.open_zip(path) as zf:
        plan = archive.inspect(zf)
        with pytest.raises(fs.NotEnoughSpaceError) as err:
            full = archive.Limits(free_margin=1 << 60)
            archive.extract(zf, plan, tmp_path / "out", limits=full, uid=UID, gid=GID)
        assert err.value.code == "not_enough_space" and not (tmp_path / "out").exists()
        (tmp_path / "taken").mkdir()
        with pytest.raises(FileExistsError):
            archive.extract(zf, plan, tmp_path / "taken", limits=NO_MARGIN, uid=UID, gid=GID)


def test_errors_keep_their_codes_and_classes() -> None:
    from hivora.games import worlds

    assert worlds.NotEnoughSpaceError is fs.NotEnoughSpaceError
    assert worlds.InvalidArchiveError is fs.InvalidArchiveError
    assert worlds.ArchiveTooLargeError is fs.ArchiveTooLargeError
    assert (fs.NotEnoughSpaceError.code, fs.InvalidArchiveError.code,
            fs.ArchiveTooLargeError.code) == ("not_enough_space", "invalid_archive",
                                              "archive_too_large")  # fmt: skip
    from hivora.core.errors import ConflictError, ValidationError

    assert issubclass(fs.NotEnoughSpaceError, ConflictError)
    assert issubclass(fs.InvalidArchiveError, ValidationError)


# --- replace_contents ----------------------------------------------------------------


def _site(root: Path) -> tuple[Path, Path]:
    html, staging = root / "app" / "html", root / "app" / ".staging"
    (html / "old").mkdir(parents=True)
    (html / "index.html").write_text("old page")
    (html / "old" / "a.css").write_text("old css")
    (html / "keep-link").symlink_to("/etc")  # moved as a link, never followed
    (staging / "new").mkdir(parents=True)
    (staging / "index.html").write_text("new page")
    (staging / "new" / "b.js").write_text("new js")
    return html, staging


def test_replace_contents_swaps_entries_and_keeps_the_folder(tmp_path: Path) -> None:
    html, staging = _site(tmp_path)
    inode = html.stat().st_ino
    assert fs.replace_contents(html, staging, tmp_path) == ["index.html", "new"]
    assert html.stat().st_ino == inode  # still the bind-mount source
    assert sorted(p.name for p in html.iterdir()) == ["index.html", "new"]
    assert (html / "index.html").read_text() == "new page"
    assert (html / "new" / "b.js").read_text() == "new js"
    assert sorted(p.name for p in (tmp_path / "app").iterdir()) == ["html"]  # nothing left
    assert Path("/etc").is_dir()


@pytest.mark.parametrize("fail_at", [1, 3, 4, 5])  # moving out, last out, first in, last in
def test_replace_contents_rolls_back_completely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    html, staging = _site(tmp_path)
    inode = html.stat().st_ino
    before = {p.name: p.read_text() if p.is_file() and not p.is_symlink() else None
              for p in html.iterdir()}  # fmt: skip
    real_rename, calls = os.rename, [0]

    def rename(src: Any, dst: Any) -> None:
        calls[0] += 1
        if calls[0] == fail_at:
            raise OSError("disk gone")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    with pytest.raises(OSError, match="disk gone"):
        fs.replace_contents(html, staging, tmp_path)
    monkeypatch.undo()

    after = {p.name: p.read_text() if p.is_file() and not p.is_symlink() else None
             for p in html.iterdir()}  # fmt: skip
    assert after == before and html.stat().st_ino == inode
    assert (html / "old" / "a.css").read_text() == "old css"
    assert (html / "keep-link").is_symlink()
    assert sorted(p.name for p in staging.iterdir()) == ["index.html", "new"]  # intact
    assert not (tmp_path / "app" / ".staging.old").exists()


def test_replace_contents_stays_inside_its_root(tmp_path: Path) -> None:
    html, staging = _site(tmp_path / "root")
    with pytest.raises(PermissionDeniedError):
        fs.replace_contents(html, staging, tmp_path / "root" / "app" / "html")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(PermissionDeniedError):
        fs.replace_contents(outside, staging, tmp_path / "root")
    assert (html / "index.html").read_text() == "old page"


def test_core_archive_imports_no_business_module() -> None:
    import ast

    for name in ("archive", "fs"):
        tree = ast.parse(Path(fs.__file__).with_name(f"{name}.py").read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        hivora = {m for m in imported if m.split(".")[0] == "hivora"}
        assert all(m.startswith("hivora.core.") for m in hivora), (name, hivora)
