"""A hosted site's content from a zip (PUT /apps/{app}/sites/{site}/content): checked at
upload, put in place by a site_content job, all at once, in the bind-mounted folder."""

import os
import stat
import time
import zipfile
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import (
    API,
    NGINX_VOLUMES,
    STRONG,
    admin,
    code,
    deploy_nginx,
    host_before_deploy,
    login,
    main_site_url,
    nginx_host,
    other_user,
    paths_under,
    site_id_of,
    spy_events,
    upload_zip,
    volumes_of,
    wait_job,
    zip_bytes,
)


def _queue_content(client: Any, app_id: int, slug: str) -> int:
    """A site_content job queued by hand, as the service does after the deploy."""
    from hivora.jobs import JobKind

    rt = client.app.state.runtime

    async def add() -> int:
        async with rt.sessions() as session, session.begin():
            job = rt.jobs.add(session, JobKind.SITE_CONTENT, app_id=app_id, app_slug=slug)
            await session.flush()
            job_id: int = job.id
        rt.jobs.wake()
        return job_id

    result: int = client.portal.call(add)
    return result


def test_an_older_first_page_job_ends_without_writing(client: Any) -> None:
    """A site_content job without an archive, as the older site creation (removed) queued
    for a first page: it succeeds, says so in its log, and writes nothing."""
    admin(client)
    app_id = nginx_host(client)
    html = volumes_of(client) / "html"
    job = wait_job(client, _queue_content(client, app_id, "vitrine"))
    assert job["status"] == "succeeded", job["error"]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "no archive: nothing to do" in log
    assert paths_under(html) == []


def test_site_html_dir_is_the_bind_mount_and_lives_next_to_uploads(client: Any) -> None:
    """<slug>/html is the main site's mount; work files next to it (uploads, staging) are
    never served, and they sit on the same filesystem, so moving them into html is a plain
    rename. The other mounts (sites, conf) are their own folders, not inside html."""
    admin(client)
    settings = client.app.state.runtime.settings
    main_site_url(client)
    app_dir = settings.volumes_root / "vitrine"
    html = app_dir / "html"

    compose = yaml.safe_load((settings.data_dir / "apps" / "vitrine" / "compose.yaml").read_text())
    mounts = [v for svc in compose["services"].values() for v in svc.get("volumes", [])]
    assert [(m["type"], m["source"], m["target"]) for m in mounts] == [
        ("bind", str(html), "/usr/share/nginx/html"),
        ("bind", str(app_dir / "sites"), "/usr/share/nginx/sites"),
        ("bind", str(app_dir / "conf"), "/etc/nginx/hivora.d"),
    ]
    assert sorted(p.name for p in app_dir.iterdir()) == NGINX_VOLUMES
    assert html.is_dir() and not html.is_symlink()
    assert html.stat().st_dev == app_dir.stat().st_dev
    assert sorted(p.name for p in html.iterdir()) == ["index.html"]


def test_replace_content_from_a_zip(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    html = volumes_of(client) / "html"
    inode = html.stat().st_ino
    body = zip_bytes(("mon-site/index.html", "<h1>new</h1>"), ("mon-site/css/a.css", "a{}"),
                ("__MACOSX/mon-site/._index.html", "junk"))  # fmt: skip
    published, undo = spy_events(client)
    try:
        sent = upload_zip(client, url, body)
        assert sent.status_code == 202, sent.text
        assert sent.json()["kind"] == "site_content"
        job = wait_job(client, sent.json()["id"])
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    assert paths_under(html) == ["css", "css/a.css", "index.html"]
    assert (html / "index.html").read_text() == "<h1>new</h1>"
    assert html.stat().st_ino == inode  # still the bind-mount source
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES  # nothing left
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "top folder mon-site/ removed" in log and "warning" not in log
    [(topic, payload)] = [(t, p) for t, p in published if t.startswith("site.")]
    expected = {"app": "vitrine", "files": 2, "bytes": 15, "filename": "site.zip",
                "site_id": site_id_of(url)}  # fmt: skip
    assert (topic, payload) == ("site.content_replaced", expected)
    time.sleep(0.8)  # the recorder writes in small batches
    audit = client.get(f"{API}/audit", params={"limit": 1000}).json()
    assert [(a["action"], a["target"]) for a in audit if a["action"].startswith("site.")] == [
        ("site.content_replaced", "vitrine"),
        ("site.hosting_enabled", "vitrine"),  # newest first
    ]


def test_bad_archives_are_refused_at_upload(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    html = volumes_of(client) / "html"
    before = (html / "index.html").read_text()
    jobs_before = client.get(f"{API}/jobs").json()
    link = zipfile.ZipInfo("index.html")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    cases = [
        (zip_bytes(("index.html", "i"), ("../evil.html", "x")), "invalid_archive", "unsafe path"),
        (zip_bytes(("/etc/evil.html", "x")), "invalid_archive", "unsafe path"),
        (zip_bytes((link, "/etc/passwd")), "invalid_archive", "symbolic link"),
        (zip_bytes(("__MACOSX/x", "x"), (".DS_Store", "x")), "invalid_archive", "empty"),
        (b"not a zip at all", "invalid_archive", "not a valid .zip"),
        (b"", "invalid_archive", "empty upload"),
    ]
    for body, error, message in cases:
        r = upload_zip(client, url, body)
        assert r.status_code == 422 and code(r) == error, (message, r.text)
        assert message in r.json()["error"]["message"]
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES  # uploads removed
    assert paths_under(html) == ["index.html"] and (html / "index.html").read_text() == before


def test_too_large_upload_is_cut(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    client.app.state.runtime.sites.max_upload = 100
    r = upload_zip(client, url, zip_bytes(("index.html", "x" * 1000)))
    assert r.status_code == 422 and code(r) == "archive_too_large"
    assert r.json()["error"]["details"] == {"limit": 100}
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES


def test_archive_without_index_is_a_warning(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    sent = upload_zip(client, url, zip_bytes(("home.html", "h"), ("img/logo.svg", "<svg/>")))
    job = wait_job(client, sent.json()["id"])
    assert job["status"] == "succeeded"
    assert paths_under(volumes_of(client) / "html") == ["home.html", "img", "img/logo.svg"]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "warning: no index.html at the root" in log


def test_leftovers_of_an_interrupted_replacement_are_swept(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    app_dir = volumes_of(client)
    (app_dir / ".hivora-staging-dead").mkdir()
    (app_dir / ".hivora-staging-dead" / "x.html").write_text("x")
    (app_dir / ".hivora-staging-dead.old").mkdir()
    old_upload, recent_upload = (
        app_dir / ".hivora-upload-old.zip",
        app_dir / ".hivora-upload-new.zip",
    )
    old_upload.write_bytes(b"x")
    recent_upload.write_bytes(b"x")  # may still belong to a queued job: kept
    day_ago = time.time() - 2 * 24 * 3600
    os.utime(old_upload, (day_ago, day_ago))
    job = wait_job(client, upload_zip(client, url, zip_bytes(("index.html", "i"))).json()["id"])
    assert job["status"] == "succeeded"
    assert sorted(p.name for p in app_dir.iterdir()) == [".hivora-upload-new.zip", *NGINX_VOLUMES]


def test_a_failed_replacement_leaves_the_site_as_it_was(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hivora.core import fs

    admin(client)
    url = main_site_url(client)
    html = volumes_of(client) / "html"
    before = (html / "index.html").read_text()

    def boom(target: Path, staging: Path, root: Path) -> list[str]:
        raise OSError("disk gone")

    monkeypatch.setattr(fs, "replace_contents", boom)
    job = wait_job(client, upload_zip(client, url, zip_bytes(("index.html", "new"))).json()["id"])
    assert job["status"] == "failed" and "disk gone" in job["error"]
    assert paths_under(html) == ["index.html"] and (html / "index.html").read_text() == before
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES  # upload, staging


def test_replacement_runs_after_the_deploy(client: Any) -> None:
    admin(client)
    deployed = deploy_nginx(client, "Vitrine", 8190).json()
    url = host_before_deploy(client, deployed["app"]["id"])
    # Sent at once, without waiting: queued behind the deploy.
    sent = upload_zip(client, url, zip_bytes(("index.html", "mine")))
    assert sent.status_code == 202, sent.text
    jobs = [wait_job(client, j) for j in (deployed["job"]["id"], sent.json()["id"])]
    assert all(j["status"] == "succeeded" for j in jobs)
    for before, after in pairwise(jobs):
        assert before["finished_at"] <= after["started_at"]
    assert (volumes_of(client) / "html" / "index.html").read_text() == "mine"


def test_replacement_needs_a_deployed_site(client: Any) -> None:
    from hivora.apps.models import Application, Origin
    from hivora.jobs import JobKind

    admin(client)
    rt = client.app.state.runtime
    upload = volumes_of(client, "brouillon") / ".hivora-upload-x.zip"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(zip_bytes(("index.html", "i")))

    async def queue() -> int:
        async with rt.sessions() as session, session.begin():
            app = Application(slug="brouillon", name="Brouillon", origin=Origin.TEMPLATE,
                              kind="static-site", created_at=rt.clock.now())  # fmt: skip
            session.add(app)
            await session.flush()
            job = rt.jobs.add(session, JobKind.SITE_CONTENT, app_id=app.id, app_slug="brouillon",
                              params={"upload": str(upload), "filename": "x.zip"})  # fmt: skip
            await session.flush()
            job_id: int = job.id
        rt.jobs.wake()
        return job_id

    failed = wait_job(client, client.portal.call(queue))
    assert failed["status"] == "failed" and "not deployed" in failed["error"]
    assert list(upload.parent.iterdir()) == []  # the upload removed, nothing written


def test_content_route_roles_and_unknown(client: Any) -> None:
    admin(client)
    manual = deploy_nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    url = main_site_url(client)
    body = zip_bytes(("index.html", "i"))
    for app_id in (manual["app"]["id"], 9999):  # a catalog nginx hosts no sites yet
        r = upload_zip(client, f"{API}/apps/{app_id}/sites/{site_id_of(url)}", body)
        assert r.status_code == 404 and code(r) == "site_not_found"
    assert sorted(p.name for p in volumes_of(client, "manuel").iterdir()) == NGINX_VOLUMES

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        r = upload_zip(viewer, url, body)
        assert r.status_code == 403 and code(r) == "insufficient_role"
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES
