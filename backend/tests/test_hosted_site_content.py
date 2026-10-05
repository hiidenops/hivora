"""Content and files of any site an nginx hosts (site_id), each confined to its own folder;
no site_id (and jobs queued before sites had rows) still means the main site."""

import functools
import io
import sqlite3
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from helpers import API, admin, wait_job

from hivora.core.errors import HivoraError


def _host(client: Any) -> tuple[int, Path, dict[str, int]]:
    """A host with two added sites (rows only, as SiteHosting writes them)."""
    admin(client)
    rt = client.app.state.runtime
    created = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8190}).json()
    wait_job(client, created["job"]["id"])
    wait_job(client, created["content_job"]["id"])
    app_id = created["site"]["id"]
    with sqlite3.connect(rt.settings.db_path) as conn:
        for slug, port in (("blog", 8096), ("wiki", 8097)):
            conn.execute("INSERT INTO site (app_id, slug, name, root, port, enabled, created_at)"
                         " VALUES (?, ?, ?, ?, ?, 1, '2026-10-05 12:00:00.000000')",
                         (app_id, slug, slug, slug, port))  # fmt: skip
        ids = dict(conn.execute("SELECT slug, id FROM site WHERE app_id = ?", (app_id,)).fetchall())
    return app_id, rt.settings.volumes_root / "vitrine", ids


def _zip(*members: tuple[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _replace(client: Any, app_id: int, body: bytes, site_id: int | None) -> Any:
    rt = client.app.state.runtime

    async def chunks() -> AsyncIterator[bytes]:
        yield body

    return client.portal.call(functools.partial(
        rt.sites.replace_content, app_id, "site.zip", chunks(), site_id=site_id))  # fmt: skip


def _files(client: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    rt = client.app.state.runtime
    return client.portal.call(functools.partial(getattr(rt.site_files, method), *args, **kwargs))


def _tree(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): p.read_text() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def _refused(client: Any, error: str, method: str, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(HivoraError) as err:
        _files(client, method, *args, **kwargs)
    assert err.value.code == error, err.value


def test_a_zip_on_an_added_site_fills_its_folder_only(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    main_before = _tree(app_dir / "html")
    published: list[tuple[str, dict[str, Any]]] = []
    bus = client.app.state.runtime.bus
    real = bus.publish

    def spy(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real(topic, **payload)

    bus.publish = spy
    try:
        job = _replace(client, app_id, _zip(("blog/index.html", "<h1>blog</h1>"),
                                            ("blog/css/a.css", "a{}")), ids["blog"])  # fmt: skip
        done = wait_job(client, job.id)
    finally:
        bus.publish = real
    assert done["status"] == "succeeded", done["error"]
    assert _tree(app_dir / "sites" / "blog") == {"index.html": "<h1>blog</h1>", "css/a.css": "a{}"}
    assert _tree(app_dir / "html") == main_before  # the main site untouched
    assert not (app_dir / "sites" / "wiki").exists()  # nor the other site
    assert sorted(p.name for p in app_dir.iterdir()) == ["conf", "html", "sites"]  # no work file
    [(_, payload)] = [(t, p) for t, p in published if t == "site.content_replaced"]
    assert payload["site_id"] == ids["blog"] and payload["files"] == 2


def test_files_of_an_added_site_live_in_its_folder(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    blog = ids["blog"]
    assert _files(client, "list", app_id, site_id=blog) == ([], False)  # no folder yet
    job = _files(client, "save", app_id, "index.html", "<h1>blog</h1>", None, site_id=blog)
    assert wait_job(client, job.id)["status"] == "succeeded"
    assert (app_dir / "sites" / "blog" / "index.html").read_text() == "<h1>blog</h1>"
    [listed], _ = _files(client, "list", app_id, site_id=blog)
    assert listed.path == "index.html"
    read = _files(client, "read", app_id, "index.html", site_id=blog)
    assert read.content == "<h1>blog</h1>"
    job = _files(client, "save", app_id, "index.html", "<h1>v2</h1>", read.sha256, site_id=blog)
    assert wait_job(client, job.id)["status"] == "succeeded"
    assert (app_dir / "sites" / "blog" / "index.html").read_text() == "<h1>v2</h1>"
    # The main site's index.html is another file.
    assert "<title>Vitrine</title>" in _files(client, "read", app_id, "index.html").content


def test_no_way_from_one_site_into_another(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    sites = app_dir / "sites"
    (sites / "wiki").mkdir()
    (sites / "wiki" / "secret.html").write_text("wiki")
    (sites / "blog").mkdir()
    (sites / "blog" / "w").symlink_to(sites / "wiki")  # a link inside blog, into wiki
    blog = ids["blog"]
    _refused(client, "invalid_path", "read", app_id, "../wiki/secret.html", site_id=blog)
    _refused(client, "invalid_path", "save", app_id, "../wiki/x.html", "x", None, site_id=blog)
    _refused(client, "permission_denied", "read", app_id, "w/secret.html", site_id=blog)
    _refused(client, "permission_denied", "save", app_id, "w/x.html", "x", None, site_id=blog)
    assert [f.path for f in _files(client, "list", app_id, site_id=blog)[0]] == []  # link skipped

    # The site's folder itself a link to another site: refused, the other site untouched.
    (sites / "blog" / "w").unlink()
    (sites / "blog").rmdir()
    (sites / "blog").symlink_to(sites / "wiki")
    _refused(client, "permission_denied", "list", app_id, site_id=blog)
    _refused(client, "permission_denied", "save", app_id, "x.html", "x", None, site_id=blog)
    with pytest.raises(HivoraError) as err:
        _replace(client, app_id, _zip(("index.html", "x")), blog)
    assert err.value.code == "permission_denied"
    assert _tree(sites / "wiki") == {"secret.html": "wiki"}


def test_a_site_of_another_app_or_unknown_is_not_found(client: Any) -> None:
    app_id, _, ids = _host(client)
    _refused(client, "site_not_found", "list", app_id, site_id=9999)
    other = client.post(f"{API}/sites", json={"name": "Autre", "port": 8191}).json()
    wait_job(client, other["job"]["id"])
    _refused(client, "site_not_found", "list", other["site"]["id"], site_id=ids["blog"])


def test_no_site_id_and_the_main_site_id_both_mean_the_main_site(client: Any) -> None:
    from hivora.jobs import JobKind

    app_id, app_dir, ids = _host(client)
    rt = client.app.state.runtime
    by_none = _files(client, "read", app_id, "index.html")
    by_main = _files(client, "read", app_id, "index.html", site_id=ids["main"])
    assert by_none == by_main and "<title>Vitrine</title>" in by_none.content

    # A site_file job queued as before sites had rows (no site_id): the main site.
    edit = app_dir / ".hivora-edit-old"
    edit.write_text("<h1>old job</h1>")

    async def queue() -> int:
        async with rt.sessions() as session, session.begin():
            job = rt.jobs.add(session, JobKind.SITE_FILE, app_id=app_id, app_slug="vitrine",
                              params={"path": "index.html", "edit": str(edit),
                                      "base_sha256": by_none.sha256, "bytes": 16})  # fmt: skip
            await session.flush()
            job_id: int = job.id
        rt.jobs.wake()
        return job_id

    assert wait_job(client, client.portal.call(queue))["status"] == "succeeded"
    assert (app_dir / "html" / "index.html").read_text() == "<h1>old job</h1>"
    assert not (app_dir / "sites" / "blog").exists()


def test_an_added_site_needs_the_sites_volume(client: Any) -> None:
    app_id, _, ids = _host(client)
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:  # as an nginx still on template 1.0.0
        conn.execute("DELETE FROM volume_mount WHERE target = '/usr/share/nginx/sites'")
    _refused(client, "host_upgrade_required", "list", app_id, site_id=ids["blog"])
    assert _files(client, "list", app_id)[0]  # the main site still works
