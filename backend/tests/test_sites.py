"""The deploy and lifecycle behaviour the sites build on (an nginx app deployed from the
catalog, then started and stopped), and a site's content: its zip and its text files."""

import io
import os
import stat
import time
import zipfile
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import API, MAIN_PAGE, STRONG, admin, code, login, nginx_host, other_user, wait_job

# The bind-mounted folders of an nginx app (template 1.1.0): the main site, the added
# sites, and the files Hivora writes for nginx. Nothing else is ever left next to them.
VOLUMES = ["conf", "html", "sites"]


def _spy(client: Any) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    """Record the events published; returns an undo."""
    bus = client.app.state.runtime.bus
    published: list[tuple[str, dict[str, Any]]] = []
    real_publish = bus.publish

    def publish(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real_publish(topic, **payload)

    bus.publish = publish

    def undo() -> None:
        bus.publish = real_publish

    return published, undo


def _nginx(client: Any, name: str, port: int) -> Any:
    body = {"template": "nginx", "name": name, "inputs": {"web_port": port}}
    return client.post(f"{API}/apps", json=body)


def test_catalog_nginx_deploy_reference(client: Any) -> None:
    admin(client)
    settings = client.app.state.runtime.settings
    deployed = _nginx(client, "Vitrine", 8180)
    assert deployed.status_code == 202, deployed.text
    app, job = deployed.json()["app"], deployed.json()["job"]
    assert (app["slug"], app["template"], app["origin"]) == ("vitrine", "nginx", "template")
    assert app["desired_state"] == "running"
    assert job["kind"] == "deploy"
    done = wait_job(client, job["id"])
    assert done["status"] == "succeeded" and done["app_id"] == app["id"]

    # The volumes are bind mounts under the volumes root, created on deploy.
    app_dir = settings.volumes_root / "vitrine"
    assert all((app_dir / name).is_dir() for name in VOLUMES)
    compose = yaml.safe_load((settings.data_dir / "apps" / "vitrine" / "compose.yaml").read_text())
    [web] = compose["services"].values()
    assert [(v["type"], v["source"], v["target"]) for v in web["volumes"]] == [
        ("bind", str(app_dir / "html"), "/usr/share/nginx/html"),
        ("bind", str(app_dir / "sites"), "/usr/share/nginx/sites"),
        ("bind", str(app_dir / "conf"), "/etc/nginx/hivora.d"),
    ]
    assert [(p["published"], p["target"]) for p in web["ports"]] == [("8180", 80)]
    assert [a["slug"] for a in client.get(f"{API}/apps").json()] == ["vitrine"]

    # The errors a site creation will reuse: port taken, slug taken.
    taken = _nginx(client, "Autre", 8180)
    assert taken.status_code == 409 and code(taken) == "port_conflict"
    body = {"template": "nginx", "name": "Vitrine", "slug": "vitrine",
            "inputs": {"web_port": 8181}}  # fmt: skip
    again = client.post(f"{API}/apps", json=body)
    assert again.status_code == 409 and code(again) == "conflict"
    assert [a["slug"] for a in client.get(f"{API}/apps").json()] == ["vitrine"]


def test_lifecycle_start_stop_reference(client: Any) -> None:
    admin(client)
    deployed = _nginx(client, "Vitrine", 8180).json()
    app_id = deployed["app"]["id"]
    wait_job(client, deployed["job"]["id"])

    published, undo = _spy(client)
    try:
        stop = client.post(f"{API}/apps/{app_id}/stop")
        assert stop.status_code == 202 and stop.json()["kind"] == "stop"
        assert client.get(f"{API}/apps/{app_id}").json()["desired_state"] == "stopped"
        assert wait_job(client, stop.json()["id"])["status"] == "succeeded"

        start = client.post(f"{API}/apps/{app_id}/start")
        assert start.status_code == 202 and start.json()["kind"] == "start"
        assert client.get(f"{API}/apps/{app_id}").json()["desired_state"] == "running"
        assert wait_job(client, start.json()["id"])["status"] == "succeeded"
    finally:
        undo()
    topics = [t for t, _ in published if t.startswith("app.")]
    assert topics == []  # start and stop publish no app.* event of their own

    missing = client.post(f"{API}/apps/9999/stop")
    assert missing.status_code == 404 and code(missing) == "app_not_found"


def test_lifecycle_refused_until_the_first_deploy_has_run(client: Any) -> None:
    """A site cannot be enabled or disabled while its deploy job is still queued."""
    admin(client)
    rt = client.app.state.runtime
    client.portal.call(rt.jobs.stop)  # freeze the queue: the deploy job stays queued
    deployed = _nginx(client, "Vitrine", 8180).json()
    refused = client.post(f"{API}/apps/{deployed['app']['id']}/stop")
    assert refused.status_code == 409 and code(refused) == "conflict"
    assert client.get(f"{API}/jobs/{deployed['job']['id']}").json()["status"] == "queued"


def test_jobs_of_one_app_run_in_order(client: Any) -> None:
    admin(client)
    deployed = _nginx(client, "Vitrine", 8180).json()
    app_id = deployed["app"]["id"]
    wait_job(client, deployed["job"]["id"])
    # Queued back to back, without waiting: the app lane runs them one after another.
    ids = [client.post(f"{API}/apps/{app_id}/{action}").json()["id"]
           for action in ("stop", "start", "restart")]  # fmt: skip
    jobs = [wait_job(client, i) for i in ids]
    assert [j["kind"] for j in jobs] == ["stop", "start", "restart"]
    assert all(j["status"] == "succeeded" for j in jobs)
    for before, after in pairwise(jobs):
        assert before["finished_at"] <= after["started_at"]


# --- S1-c: the sites module -------------------------------------------------------------


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
    html = _app_dir(client) / "html"
    job = wait_job(client, _queue_content(client, app_id, "vitrine"))
    assert job["status"] == "succeeded", job["error"]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "no archive: nothing to do" in log
    assert _listing(html) == []


# --- S2-a: what the zip replacement builds on --------------------------------------------


def test_site_html_dir_is_the_bind_mount_and_lives_next_to_uploads(client: Any) -> None:
    """<slug>/html is the main site's mount; work files next to it (uploads, staging) are
    never served, and they sit on the same filesystem, so moving them into html is a plain
    rename. The other mounts (sites, conf) are their own folders, not inside html."""
    admin(client)
    settings = client.app.state.runtime.settings
    _main(client)
    app_dir = settings.volumes_root / "vitrine"
    html = app_dir / "html"

    compose = yaml.safe_load((settings.data_dir / "apps" / "vitrine" / "compose.yaml").read_text())
    mounts = [v for svc in compose["services"].values() for v in svc.get("volumes", [])]
    assert [(m["type"], m["source"], m["target"]) for m in mounts] == [
        ("bind", str(html), "/usr/share/nginx/html"),
        ("bind", str(app_dir / "sites"), "/usr/share/nginx/sites"),
        ("bind", str(app_dir / "conf"), "/etc/nginx/hivora.d"),
    ]
    assert sorted(p.name for p in app_dir.iterdir()) == VOLUMES
    assert html.is_dir() and not html.is_symlink()
    assert html.stat().st_dev == app_dir.stat().st_dev
    assert sorted(p.name for p in html.iterdir()) == ["index.html"]


# --- S2-c: replacing a site's content from a zip -----------------------------------------


def _zip(*members: Any) -> bytes:
    """Members: (name, data) or (ZipInfo, data)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _main(client: Any) -> str:
    """A host whose main site has a page: the main site's base on the hosted routes."""
    app_id = nginx_host(client)
    (_app_dir(client) / "html" / "index.html").write_text(MAIN_PAGE)
    main = client.get(f"{API}/apps/{app_id}/sites").json()["sites"][0]["id"]
    return f"{API}/apps/{app_id}/sites/{main}"


def _id(url: str) -> int:
    """The site's id, last in its base."""
    return int(url.rsplit("/", 1)[1])


def _queued_host(client: Any, app_id: int) -> str:
    """An nginx whose deploy has not run yet starts hosting: its main site's base."""
    hosted = client.post(f"{API}/apps/{app_id}/sites/hosting")
    assert hosted.status_code == 200, hosted.text
    return f"{API}/apps/{app_id}/sites/{hosted.json()['sites'][0]['id']}"


def _upload(client: Any, base: str, body: bytes, filename: str = "site.zip") -> Any:
    return client.put(f"{base}/content", params={"filename": filename},
                      content=body, headers={"content-type": "application/zip"})  # fmt: skip


def _app_dir(client: Any, slug: str = "vitrine") -> Path:
    path: Path = client.app.state.runtime.settings.volumes_root / slug
    return path


def _listing(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def test_replace_content_from_a_zip(client: Any) -> None:
    admin(client)
    url = _main(client)
    html = _app_dir(client) / "html"
    inode = html.stat().st_ino
    body = _zip(("mon-site/index.html", "<h1>new</h1>"), ("mon-site/css/a.css", "a{}"),
                ("__MACOSX/mon-site/._index.html", "junk"))  # fmt: skip
    published, undo = _spy(client)
    try:
        sent = _upload(client, url, body)
        assert sent.status_code == 202, sent.text
        assert sent.json()["kind"] == "site_content"
        job = wait_job(client, sent.json()["id"])
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    assert _listing(html) == ["css", "css/a.css", "index.html"]
    assert (html / "index.html").read_text() == "<h1>new</h1>"
    assert html.stat().st_ino == inode  # still the bind-mount source
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES  # nothing left
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "top folder mon-site/ removed" in log and "warning" not in log
    [(topic, payload)] = [(t, p) for t, p in published if t.startswith("site.")]
    assert (topic, payload) == ("site.content_replaced", {
        "app": "vitrine", "files": 2, "bytes": 15, "filename": "site.zip", "site_id": _id(url),
    })  # fmt: skip
    time.sleep(0.8)  # the recorder writes in small batches
    audit = client.get(f"{API}/audit", params={"limit": 1000}).json()
    assert [(a["action"], a["target"]) for a in audit if a["action"].startswith("site.")] == [
        ("site.content_replaced", "vitrine"),
        ("site.hosting_enabled", "vitrine"),  # newest first
    ]


def test_bad_archives_are_refused_at_upload(client: Any) -> None:
    admin(client)
    url = _main(client)
    html = _app_dir(client) / "html"
    before = (html / "index.html").read_text()
    jobs_before = client.get(f"{API}/jobs").json()
    link = zipfile.ZipInfo("index.html")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    cases = [
        (_zip(("index.html", "i"), ("../evil.html", "x")), "invalid_archive", "unsafe path"),
        (_zip(("/etc/evil.html", "x")), "invalid_archive", "unsafe path"),
        (_zip((link, "/etc/passwd")), "invalid_archive", "symbolic link"),
        (_zip(("__MACOSX/x", "x"), (".DS_Store", "x")), "invalid_archive", "empty"),
        (b"not a zip at all", "invalid_archive", "not a valid .zip"),
        (b"", "invalid_archive", "empty upload"),
    ]
    for body, error, message in cases:
        r = _upload(client, url, body)
        assert r.status_code == 422 and code(r) == error, (message, r.text)
        assert message in r.json()["error"]["message"]
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES  # uploads removed
    assert _listing(html) == ["index.html"] and (html / "index.html").read_text() == before


def test_too_large_upload_is_cut(client: Any) -> None:
    admin(client)
    url = _main(client)
    client.app.state.runtime.sites.max_upload = 100
    r = _upload(client, url, _zip(("index.html", "x" * 1000)))
    assert r.status_code == 422 and code(r) == "archive_too_large"
    assert r.json()["error"]["details"] == {"limit": 100}
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES


def test_archive_without_index_is_a_warning(client: Any) -> None:
    admin(client)
    url = _main(client)
    sent = _upload(client, url, _zip(("home.html", "h"), ("img/logo.svg", "<svg/>")))
    job = wait_job(client, sent.json()["id"])
    assert job["status"] == "succeeded"
    assert _listing(_app_dir(client) / "html") == ["home.html", "img", "img/logo.svg"]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "warning: no index.html at the root" in log


def test_leftovers_of_an_interrupted_replacement_are_swept(client: Any) -> None:
    admin(client)
    url = _main(client)
    app_dir = _app_dir(client)
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
    job = wait_job(client, _upload(client, url, _zip(("index.html", "i"))).json()["id"])
    assert job["status"] == "succeeded"
    assert sorted(p.name for p in app_dir.iterdir()) == [".hivora-upload-new.zip", *VOLUMES]


def test_a_failed_replacement_leaves_the_site_as_it_was(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hivora.core import fs

    admin(client)
    url = _main(client)
    html = _app_dir(client) / "html"
    before = (html / "index.html").read_text()

    def boom(target: Path, staging: Path, root: Path) -> list[str]:
        raise OSError("disk gone")

    monkeypatch.setattr(fs, "replace_contents", boom)
    job = wait_job(client, _upload(client, url, _zip(("index.html", "new"))).json()["id"])
    assert job["status"] == "failed" and "disk gone" in job["error"]
    assert _listing(html) == ["index.html"] and (html / "index.html").read_text() == before
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES  # upload, staging


def test_replacement_runs_after_the_deploy(client: Any) -> None:
    admin(client)
    deployed = _nginx(client, "Vitrine", 8190).json()
    url = _queued_host(client, deployed["app"]["id"])
    # Sent at once, without waiting: queued behind the deploy.
    sent = _upload(client, url, _zip(("index.html", "mine")))
    assert sent.status_code == 202, sent.text
    jobs = [wait_job(client, j) for j in (deployed["job"]["id"], sent.json()["id"])]
    assert all(j["status"] == "succeeded" for j in jobs)
    for before, after in pairwise(jobs):
        assert before["finished_at"] <= after["started_at"]
    assert (_app_dir(client) / "html" / "index.html").read_text() == "mine"


def test_replacement_needs_a_deployed_site(client: Any) -> None:
    from hivora.apps.models import Application, Origin
    from hivora.jobs import JobKind

    admin(client)
    rt = client.app.state.runtime
    upload = _app_dir(client, "brouillon") / ".hivora-upload-x.zip"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(_zip(("index.html", "i")))

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
    manual = _nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    url = _main(client)
    body = _zip(("index.html", "i"))
    for app_id in (manual["app"]["id"], 9999):  # a catalog nginx hosts no sites yet
        r = _upload(client, f"{API}/apps/{app_id}/sites/{_id(url)}", body)
        assert r.status_code == 404 and code(r) == "site_not_found"
    assert sorted(p.name for p in _app_dir(client, "manuel").iterdir()) == VOLUMES

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        r = _upload(viewer, url, body)
        assert r.status_code == 403 and code(r) == "insufficient_role"
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES


# --- S3-c: reading and editing a site's text files ---------------------------------------


def _read(client: Any, url: str, path: str) -> Any:
    return client.get(f"{url}/files/content", params={"path": path})


def _save(client: Any, url: str, path: str, content: str, base: str | None) -> Any:
    body = {"path": path, "content": content, "base_sha256": base}
    return client.put(f"{url}/files/content", json=body)


def test_edit_a_file_through_its_job(client: Any) -> None:
    admin(client)
    url = _main(client)
    html = _app_dir(client) / "html"
    base = _read(client, url, "index.html").json()["sha256"]
    published, undo = _spy(client)
    try:
        saved = _save(client, url, "index.html", "<h1>Bienvenue</h1>", base)
        assert saved.status_code == 202, saved.text
        assert saved.json()["kind"] == "site_file"
        job = wait_job(client, saved.json()["id"])
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    assert (html / "index.html").read_text() == "<h1>Bienvenue</h1>"
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES  # nothing staged
    events = [(t, p) for t, p in published if t.startswith("site.")]
    assert events == [("site.file_saved", {"app": "vitrine", "path": "index.html", "bytes": 18,
                                           "created": False, "site_id": _id(url)})]  # fmt: skip
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert "Bienvenue" not in detail["log"] and "index.html (18 bytes)" in detail["log"]
    time.sleep(0.8)  # the recorder writes in small batches
    audit = [a for a in client.get(f"{API}/audit", params={"limit": 1000}).json()
             if a["action"] == "site.file_saved"]  # fmt: skip
    assert [(a["target"], a["payload"]["path"]) for a in audit] == [("vitrine", "index.html")]
    assert "Bienvenue" not in str(audit)  # never the content

    stale = _save(client, url, "index.html", "late", base)  # read before the edit
    assert stale.status_code == 409 and code(stale) == "file_changed"
    assert (html / "index.html").read_text() == "<h1>Bienvenue</h1>"


def test_create_a_file_in_new_folders(client: Any) -> None:
    admin(client)
    url = _main(client)
    saved = _save(client, url, "css/theme/main.css", "body{margin:0}", None)
    job = wait_job(client, saved.json()["id"])
    assert job["status"] == "succeeded"
    assert "created css/theme/main.css" in client.get(f"{API}/jobs/{job['id']}").json()["log"]
    paths = [f["path"] for f in client.get(f"{url}/files").json()["files"]]
    assert paths == ["css/theme/main.css", "index.html"]
    again = _save(client, url, "css/theme/main.css", "x", None)
    assert again.status_code == 409 and code(again) == "file_changed"


def test_bad_edits_are_refused_before_any_job(client: Any) -> None:
    admin(client)
    url = _main(client)
    html = _app_dir(client) / "html"
    (html / "nul.html").write_bytes(b"a\x00b")
    (html / "link.html").symlink_to(html / "index.html")
    base = _read(client, url, "index.html").json()["sha256"]
    jobs_before = client.get(f"{API}/jobs").json()
    cases = [
        (_save(client, url, "../evil.html", "x", None), 422, "invalid_path"),
        (_save(client, url, "shell.php", "x", None), 422, "file_not_editable"),
        (_save(client, url, "index.html", "a\x00b", base), 422, "not_text"),
        (_save(client, url, "index.html", "é" * 600_000, base), 422, "file_too_large"),
        (_save(client, url, "index.html", "x", "0" * 64), 409, "file_changed"),
        (_save(client, url, "gone.html", "x", base), 404, "site_file_not_found"),
        (_save(client, url, "link.html", "x", None), 403, "permission_denied"),
        (_save(client, url, "index.html", "x", "not-a-hash"), 422, "request_invalid"),
        (_read(client, url, "nul.html"), 422, "not_text"),
        (_read(client, url, "link.html"), 403, "permission_denied"),
        (_read(client, url, "gone.html"), 404, "site_file_not_found"),
        (_read(client, url, "../../etc/passwd.html"), 422, "invalid_path"),
    ]
    for r, status, error in cases:
        assert (r.status_code, code(r)) == (status, error), r.text
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES  # nothing staged
    assert "<title>Vitrine</title>" in (html / "index.html").read_text()


def test_a_zip_applied_in_between_wins_over_a_stale_edit(client: Any) -> None:
    admin(client)
    url = _main(client)
    base = _read(client, url, "index.html").json()["sha256"]
    zipped = _upload(client, url, _zip(("index.html", "from the zip")))
    saved = _save(client, url, "index.html", "stale edit", base)  # sent right after
    assert wait_job(client, zipped.json()["id"])["status"] == "succeeded"
    if saved.status_code == 202:  # queued before the zip was applied: refused by the job
        job = wait_job(client, saved.json()["id"])
        assert job["status"] == "failed" and "changed since it was read" in job["error"]
    else:  # the zip was already applied: refused at once
        assert saved.status_code == 409 and code(saved) == "file_changed"
    assert (_app_dir(client) / "html" / "index.html").read_text() == "from the zip"
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES


def test_old_staged_edits_are_swept(client: Any) -> None:
    admin(client)
    url = _main(client)
    app_dir = _app_dir(client)
    old, recent = app_dir / ".hivora-edit-old", app_dir / ".hivora-edit-new"
    old.write_text("x")
    recent.write_text("x")  # may belong to a queued job: kept
    day_ago = time.time() - 2 * 24 * 3600
    os.utime(old, (day_ago, day_ago))
    base = _read(client, url, "index.html").json()["sha256"]
    job = wait_job(client, _save(client, url, "index.html", "x", base).json()["id"])
    assert job["status"] == "succeeded"
    assert sorted(p.name for p in app_dir.iterdir()) == [".hivora-edit-new", *VOLUMES]


def test_file_routes_roles_and_unknown(client: Any) -> None:
    admin(client)
    manual = _nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    url = _main(client)
    base = _read(client, url, "index.html").json()["sha256"]
    for app_id in (manual["app"]["id"], 9999):  # a catalog nginx hosts no sites yet
        other = f"{API}/apps/{app_id}/sites/{_id(url)}"
        for r in (
            client.get(f"{other}/files"),
            _read(client, other, "index.html"),
            _save(client, other, "index.html", "x", None),
        ):
            assert r.status_code == 404 and code(r) == "site_not_found"

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{url}/files").status_code == 200
        assert _read(viewer, url, "index.html").json()["sha256"] == base
        r = _save(viewer, url, "index.html", "x", base)
        assert r.status_code == 403 and code(r) == "insufficient_role"


def test_editing_needs_a_deployed_site(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    client.portal.call(rt.jobs.stop)  # the deploy job stays queued
    url = _queued_host(client, _nginx(client, "Vitrine", 8190).json()["app"]["id"])
    assert client.get(f"{url}/files").json() == {"files": [], "truncated": False}
    refused = _save(client, url, "index.html", "x", None)
    assert refused.status_code == 409 and code(refused) == "conflict"
    assert "not deployed" in refused.json()["error"]["message"]


def test_a_staged_edit_is_removed_if_it_cannot_be_queued(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin(client)
    url = _main(client)
    base = _read(client, url, "index.html").json()["sha256"]

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(client.app.state.runtime.jobs, "add", broken)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        _save(client, url, "index.html", "x", base)
    assert sorted(p.name for p in _app_dir(client).iterdir()) == VOLUMES
