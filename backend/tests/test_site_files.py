"""sites.files: the rules for a site's text files, reading them and the atomic write."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from hivora.core.errors import HivoraError, PermissionDeniedError
from hivora.sites import files as f

UID, GID = os.getuid(), os.getgid()


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """<tmp>/app/html with a page, a stylesheet in a folder, and files never listed."""
    html = tmp_path / "app" / "html"
    (html / "css").mkdir(parents=True)
    (html / "index.html").write_text("<h1>hi</h1>\n")
    (html / "css" / "site.css").write_text("a{}")
    (html / "logo.png").write_bytes(b"\x89PNG\0")
    (html / "notes.txt").write_text("x")
    return html


def edit(site: Path, rel: str, content: str, base: str | None) -> bool:
    """Stage then apply, as the route and the job will."""
    staged = site.parent / ".hivora-edit-test"
    f.stage_edit(site, rel, content, base, staged, uid=UID, gid=GID)
    return f.apply_edit(site, rel, staged, base, uid=UID, gid=GID)


def leftovers(site: Path) -> list[str]:
    return sorted(p.name for p in site.parent.iterdir() if p.name != "html")


@pytest.mark.parametrize(
    "rel",
    ["", "/etc/x.html", "../x.html", "a/../../x.html", "./x.html", "a/./x.html", "a//x.html",
     "a\\x.html", "x\x00.html", "/".join(["d"] * 32) + "/x.html", "a" * 256 + ".html",
     "/".join(["d" * 200] * 6) + "/x.html"],
)  # fmt: skip
def test_bad_paths_are_refused(rel: str) -> None:
    with pytest.raises(f.InvalidPathError) as err:
        f.check_path(rel)
    assert err.value.code == "invalid_path"


@pytest.mark.parametrize("rel", ["index.HTML", "css/Site.Css", "js/app.js", "a/b/c.html"])
def test_editable_extensions(rel: str) -> None:
    assert str(f.check_path(rel)) == rel


@pytest.mark.parametrize(
    "rel", ["x.php", "logo.svg", "data.json", "index.html.bak", "README", ".html", "css"]
)
def test_other_files_are_not_editable(rel: str) -> None:
    with pytest.raises(f.FileNotEditableError) as err:
        f.check_path(rel)
    assert err.value.code == "file_not_editable"


def test_links_on_the_path_are_refused(site: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.html").write_text("secret")
    (site / "out").symlink_to(outside)  # a folder link going out
    (site / "inner.html").symlink_to(site / "index.html")  # a file link staying inside
    (site / "loop").symlink_to(site)  # a folder link staying inside
    for rel in ("out/x.html", "inner.html", "loop/index.html"):
        with pytest.raises(PermissionDeniedError):
            f.read_file(site, rel)
    with pytest.raises(PermissionDeniedError):
        edit(site, "out/new.html", "x", None)
    assert sorted(p.name for p in outside.iterdir()) == ["x.html"]


def test_list_shows_editable_regular_files_only(site: Path, tmp_path: Path) -> None:
    (site / "js").mkdir()
    (site / "js" / "app.JS").write_text("1")
    (site / "link.html").symlink_to(site / "index.html")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.css").write_text("x")
    (site / "out").symlink_to(tmp_path / "outside")  # not followed
    os.mkfifo(site / "pipe.html")
    files, cut = f.list_files(site)
    assert [x.path for x in files] == ["css/site.css", "index.html", "js/app.JS"]
    assert cut is False and files[1].size == len("<h1>hi</h1>\n") and files[1].modified > 0

    files, cut = f.list_files(site, limit=2)
    assert [x.path for x in files] == ["css/site.css", "index.html"] and cut is True


def test_read_returns_text_and_its_hash(site: Path) -> None:
    (site / "crlf.html").write_bytes("﻿é\r\nfin".encode())
    page = f.read_file(site, "crlf.html")
    assert page.content == "﻿é\r\nfin"  # BOM and line ends kept
    assert page.size == len("﻿é\r\nfin".encode())
    assert page.sha256 == f.sha256((site / "crlf.html").read_bytes())


def test_read_refuses_binary_large_missing_and_non_files(site: Path) -> None:
    (site / "nul.html").write_bytes(b"a\x00b")
    (site / "latin.css").write_bytes("é".encode("latin-1"))
    (site / "big.js").write_bytes(b"x" * 11)
    (site / "dir.html").mkdir()
    cases: list[tuple[str, str, dict[str, Any]]] = [
        ("nul.html", "not_text", {}),
        ("latin.css", "not_text", {}),
        ("big.js", "file_too_large", {"max_size": 10}),
        ("missing.html", "site_file_not_found", {}),
        ("dir.html", "file_not_editable", {}),
    ]
    for rel, error, extra in cases:
        with pytest.raises(HivoraError) as err:
            f.read_file(site, rel, **extra)
        assert err.value.code == error, rel
    assert f.read_file(site, "big.js", max_size=11).content == "x" * 11  # at the limit


def test_edit_replaces_atomically(site: Path) -> None:
    page = f.read_file(site, "index.html")
    assert edit(site, "index.html", "<h1>new</h1>", page.sha256) is False
    assert (site / "index.html").read_text() == "<h1>new</h1>"
    assert stat.S_IMODE((site / "index.html").stat().st_mode) == 0o644
    assert leftovers(site) == []  # the staged file was moved, not copied


def test_edit_creates_a_file_and_its_folders(site: Path) -> None:
    assert edit(site, "blog/2026/post.html", "<p>post</p>", None) is True
    assert (site / "blog" / "2026" / "post.html").read_text() == "<p>post</p>"
    for folder in (site / "blog", site / "blog" / "2026"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o755
    with pytest.raises(f.FileChangedError):  # creating over an existing file
        edit(site, "index.html", "x", None)
    with pytest.raises(f.InvalidPathError):  # a parent that is a file
        edit(site, "index.html/x.html", "x", None)
    assert leftovers(site) == []


def test_edit_refuses_a_stale_base(site: Path) -> None:
    old = f.read_file(site, "index.html").sha256
    edit(site, "index.html", "first", old)
    with pytest.raises(f.FileChangedError) as err:
        edit(site, "index.html", "second", old)  # read before the first edit
    assert err.value.code == "file_changed"
    assert (site / "index.html").read_text() == "first" and leftovers(site) == []
    with pytest.raises(f.SiteFileNotFoundError):
        edit(site, "gone.html", "x", old)


def test_the_base_is_checked_again_when_applied(site: Path) -> None:
    page = f.read_file(site, "index.html")
    staged = site.parent / ".hivora-edit-test"
    f.stage_edit(site, "index.html", "mine", page.sha256, staged, uid=UID, gid=GID)
    (site / "index.html").write_text("changed meanwhile (a zip, another editor)")
    with pytest.raises(f.FileChangedError):
        f.apply_edit(site, "index.html", staged, page.sha256, uid=UID, gid=GID)
    assert (site / "index.html").read_text() == "changed meanwhile (a zip, another editor)"
    assert leftovers(site) == []  # the staged file removed


def test_edit_refuses_binary_and_large_content(site: Path) -> None:
    base = f.read_file(site, "index.html").sha256
    staged = site.parent / ".hivora-edit-test"
    with pytest.raises(f.NotTextError):
        f.stage_edit(site, "index.html", "a\x00b", base, staged, uid=UID, gid=GID)
    with pytest.raises(f.FileTooLargeError):
        f.stage_edit(site, "index.html", "é" * 6, base, staged, uid=UID, gid=GID, max_size=11)
    assert leftovers(site) == [] and (site / "index.html").read_text() == "<h1>hi</h1>\n"


def test_a_failed_replace_leaves_the_file_as_it_was(
    site: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inode = (site / "index.html").stat().st_ino
    base = f.read_file(site, "index.html").sha256
    staged = site.parent / ".hivora-edit-test"
    f.stage_edit(site, "index.html", "new", base, staged, uid=UID, gid=GID)

    def boom(src: Any, dst: Any) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk gone"):
        f.apply_edit(site, "index.html", staged, base, uid=UID, gid=GID)
    monkeypatch.undo()
    assert (site / "index.html").read_text() == "<h1>hi</h1>\n"
    assert (site / "index.html").stat().st_ino == inode
    assert leftovers(site) == []  # the staged file removed


def test_errors_and_codes() -> None:
    from hivora.core.errors import ConflictError, NotFoundError, ValidationError

    codes = {
        f.InvalidPathError: ("invalid_path", ValidationError),
        f.FileNotEditableError: ("file_not_editable", ValidationError),
        f.NotTextError: ("not_text", ValidationError),
        f.FileTooLargeError: ("file_too_large", ValidationError),
        f.FileChangedError: ("file_changed", ConflictError),
        f.SiteFileNotFoundError: ("site_file_not_found", NotFoundError),
    }
    for cls, (code, parent) in codes.items():
        assert cls.code == code and issubclass(cls, parent)
