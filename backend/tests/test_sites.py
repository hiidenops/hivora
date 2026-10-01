"""The deploy and lifecycle behaviour the static-site manager builds on, pinned before it
exists: a site is an nginx app deployed from the catalog, then started and stopped."""

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
from helpers import API, STRONG, admin, code, login, other_user, wait_job


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

    # The html volume is a bind mount under the volumes root, created on deploy.
    html = settings.volumes_root / "vitrine" / "html"
    assert html.is_dir()
    compose = yaml.safe_load((settings.data_dir / "apps" / "vitrine" / "compose.yaml").read_text())
    [web] = compose["services"].values()
    [volume] = web["volumes"]
    assert (volume["type"], volume["source"], volume["target"]) == (
        "bind",
        str(html),
        "/usr/share/nginx/html",
    )
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


def _kind(client: Any, app_id: int) -> str | None:
    from hivora.apps.models import Application

    rt = client.app.state.runtime

    async def read() -> str | None:
        async with rt.sessions() as session:
            kind: str | None = (await session.get_one(Application, app_id)).kind
        return kind

    result: str | None = client.portal.call(read)
    return result


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


def _site(client: Any, name: str = "Vitrine", port: int = 8190) -> dict[str, Any]:
    created = client.post(f"{API}/sites", json={"name": name, "port": port})
    assert created.status_code == 202, created.text
    body: dict[str, Any] = created.json()
    wait_job(client, body["job"]["id"])
    wait_job(client, body["content_job"]["id"])
    return body


def test_list_only_static_sites(client: Any) -> None:
    admin(client)
    manual = _nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    site = _site(client)["site"]

    assert _kind(client, manual["app"]["id"]) is None  # catalog nginx: not a site
    assert _kind(client, site["id"]) == "static-site"
    [listed] = client.get(f"{API}/sites").json()
    assert listed == {**listed, "id": site["id"], "slug": "vitrine", "name": "Vitrine",
                      "port": 8190, "zone_id": None, "enabled": True, "deployed": True}  # fmt: skip
    assert {a["slug"] for a in client.get(f"{API}/apps").json()} == {"manuel", "vitrine"}


def test_create_site_queues_deploy_then_content(client: Any) -> None:
    admin(client)
    settings = client.app.state.runtime.settings
    published, undo = _spy(client)
    try:
        created = client.post(f"{API}/sites", json={"name": "<Vitrine & co>", "port": 8190})
    finally:
        undo()
    assert created.status_code == 202, created.text
    body = created.json()
    assert (body["job"]["kind"], body["content_job"]["kind"]) == ("deploy", "site_content")
    assert body["site"]["deployed"] is False and body["site"]["port"] == 8190
    deploy = wait_job(client, body["job"]["id"])
    content = wait_job(client, body["content_job"]["id"])
    assert deploy["status"] == content["status"] == "succeeded"
    assert deploy["finished_at"] <= content["started_at"]  # same lane, in order
    assert any(t == "app.created" and p["template"] == "nginx" for t, p in published)

    slug = body["site"]["slug"]
    index = settings.volumes_root / slug / "html" / "index.html"
    page = index.read_text()
    assert "<title>&lt;Vitrine &amp; co&gt;</title>" in page and "<Vitrine" not in page
    assert index.stat().st_mode & 0o777 == 0o644


def test_create_site_errors_match_deploy(client: Any) -> None:
    admin(client)
    wait_job(client, _nginx(client, "Manuel", 8190).json()["job"]["id"])
    jobs_before = client.get(f"{API}/jobs").json()

    taken = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8190})
    assert taken.status_code == 409 and code(taken) == "port_conflict"
    zone = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8191, "zone": "nope"})
    assert zone.status_code == 404 and code(zone) == "zone_not_found"
    bad = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 0})
    assert bad.status_code == 422

    assert client.get(f"{API}/sites").json() == []
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued


def test_site_content_never_overwrites_and_needs_a_deploy(client: Any, tmp_path: Any) -> None:
    from hivora.apps.models import Application, Origin

    admin(client)
    rt = client.app.state.runtime
    site = _site(client)["site"]
    index = rt.settings.volumes_root / "vitrine" / "html" / "index.html"

    # An existing page is kept as it is.
    index.write_text("mine")
    kept = wait_job(client, _queue_content(client, site["id"], "vitrine"))
    assert kept["status"] == "succeeded" and index.read_text() == "mine"

    # A link out of the volumes root is refused, nothing written outside.
    outside = tmp_path / "outside"
    outside.mkdir()
    html = index.parent
    index.unlink()
    html.rmdir()
    html.symlink_to(outside)
    refused = wait_job(client, _queue_content(client, site["id"], "vitrine"))
    assert refused["status"] == "failed" and "outside of its root" in refused["error"]
    assert list(outside.iterdir()) == []

    # A site whose deploy never ran: the job fails, nothing written.
    async def undeployed() -> int:
        async with rt.sessions() as session, session.begin():
            app = Application(slug="brouillon", name="Brouillon", origin=Origin.TEMPLATE,
                              kind="static-site", created_at=rt.clock.now())  # fmt: skip
            session.add(app)
            await session.flush()
            app_id: int = app.id
        return app_id

    app_id = client.portal.call(undeployed)
    failed = wait_job(client, _queue_content(client, app_id, "brouillon"))
    assert failed["status"] == "failed" and "not deployed" in failed["error"]
    assert not (rt.settings.volumes_root / "brouillon").exists()


def test_enable_disable_through_lifecycle(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
    published, undo = _spy(client)
    try:
        off = client.put(f"{API}/sites/{site['id']}/enabled", json={"enabled": False})
        assert off.status_code == 202 and off.json()["kind"] == "stop"
        assert wait_job(client, off.json()["id"])["status"] == "succeeded"
        assert client.get(f"{API}/sites").json()[0]["enabled"] is False
        on = client.put(f"{API}/sites/{site['id']}/enabled", json={"enabled": True})
        assert on.status_code == 202 and on.json()["kind"] == "start"
        assert wait_job(client, on.json()["id"])["status"] == "succeeded"
        assert client.get(f"{API}/sites").json()[0]["enabled"] is True
    finally:
        undo()
    assert [(t, p) for t, p in published if t.startswith("site.")] == [
        ("site.disabled", {"app": "vitrine", "job": off.json()["id"]}),
        ("site.enabled", {"app": "vitrine", "job": on.json()["id"]}),
    ]
    time.sleep(0.8)  # the recorder writes in small batches
    audit = client.get(f"{API}/audit", params={"limit": 1000}).json()
    rows = [(a["action"], a["target"], a["username"]) for a in audit
            if a["action"].startswith("site.")]  # fmt: skip
    assert rows == [("site.enabled", "vitrine", "admin"), ("site.disabled", "vitrine", "admin")]


def test_enable_refused_until_the_first_deploy_has_run(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    client.portal.call(rt.jobs.stop)  # the deploy job stays queued
    created = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8190}).json()
    refused = client.put(f"{API}/sites/{created['site']['id']}/enabled", json={"enabled": False})
    assert refused.status_code == 409 and code(refused) == "conflict"
    [site] = client.get(f"{API}/sites").json()
    assert site["deployed"] is False and site["enabled"] is True


def test_sites_routes_roles_and_unknown(client: Any) -> None:
    admin(client)
    manual = _nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    site = _site(client)["site"]
    for app_id in (manual["app"]["id"], 9999):  # a catalog nginx is not a site
        r = client.put(f"{API}/sites/{app_id}/enabled", json={"enabled": False})
        assert r.status_code == 404 and code(r) == "site_not_found"

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert [s["id"] for s in viewer.get(f"{API}/sites").json()] == [site["id"]]
        for r in (
            viewer.post(f"{API}/sites", json={"name": "Autre", "port": 8191}),
            viewer.put(f"{API}/sites/{site['id']}/enabled", json={"enabled": False}),
        ):
            assert r.status_code == 403 and code(r) == "insufficient_role"


# --- S2-a: what the zip replacement builds on --------------------------------------------


def test_site_html_dir_is_the_bind_mount_and_lives_next_to_uploads(client: Any) -> None:
    """Only <slug>/html is mounted: files next to it (uploads, staging) are never served,
    and they sit on the same filesystem, so moving them into html is a plain rename."""
    admin(client)
    settings = client.app.state.runtime.settings
    site = _site(client)["site"]
    app_dir = settings.volumes_root / site["slug"]
    html = app_dir / "html"

    compose = yaml.safe_load(
        (settings.data_dir / "apps" / site["slug"] / "compose.yaml").read_text()
    )
    mounts = [v for svc in compose["services"].values() for v in svc.get("volumes", [])]
    assert [(m["type"], m["source"], m["target"]) for m in mounts] == [
        ("bind", str(html), "/usr/share/nginx/html")
    ]
    assert sorted(p.name for p in app_dir.iterdir()) == ["html"]
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


def _upload(client: Any, app_id: int, body: bytes, filename: str = "site.zip") -> Any:
    return client.put(f"{API}/sites/{app_id}/content", params={"filename": filename},
                      content=body, headers={"content-type": "application/zip"})  # fmt: skip


def _app_dir(client: Any, slug: str = "vitrine") -> Path:
    path: Path = client.app.state.runtime.settings.volumes_root / slug
    return path


def _listing(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def test_replace_content_from_a_zip(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
    html = _app_dir(client) / "html"
    inode = html.stat().st_ino
    body = _zip(("mon-site/index.html", "<h1>new</h1>"), ("mon-site/css/a.css", "a{}"),
                ("__MACOSX/mon-site/._index.html", "junk"))  # fmt: skip
    published, undo = _spy(client)
    try:
        sent = _upload(client, site["id"], body)
        assert sent.status_code == 202, sent.text
        assert sent.json()["kind"] == "site_content"
        job = wait_job(client, sent.json()["id"])
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    assert _listing(html) == ["css", "css/a.css", "index.html"]
    assert (html / "index.html").read_text() == "<h1>new</h1>"
    assert html.stat().st_ino == inode  # still the bind-mount source
    assert sorted(p.name for p in _app_dir(client).iterdir()) == ["html"]  # nothing left
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "top folder mon-site/ removed" in log and "warning" not in log
    [(topic, payload)] = [(t, p) for t, p in published if t.startswith("site.")]
    assert (topic, payload) == ("site.content_replaced", {"app": "vitrine", "files": 2,
                                "bytes": 15, "filename": "site.zip"})  # fmt: skip
    time.sleep(0.8)  # the recorder writes in small batches
    audit = client.get(f"{API}/audit", params={"limit": 1000}).json()
    assert [(a["action"], a["target"]) for a in audit if a["action"].startswith("site.")] == [
        ("site.content_replaced", "vitrine")
    ]


def test_bad_archives_are_refused_at_upload(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
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
        r = _upload(client, site["id"], body)
        assert r.status_code == 422 and code(r) == error, (message, r.text)
        assert message in r.json()["error"]["message"]
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued
    assert sorted(p.name for p in _app_dir(client).iterdir()) == ["html"]  # uploads removed
    assert _listing(html) == ["index.html"] and (html / "index.html").read_text() == before


def test_too_large_upload_is_cut(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
    client.app.state.runtime.sites.max_upload = 100
    r = _upload(client, site["id"], _zip(("index.html", "x" * 1000)))
    assert r.status_code == 422 and code(r) == "archive_too_large"
    assert r.json()["error"]["details"] == {"limit": 100}
    assert sorted(p.name for p in _app_dir(client).iterdir()) == ["html"]


def test_archive_without_index_is_a_warning(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
    sent = _upload(client, site["id"], _zip(("home.html", "h"), ("img/logo.svg", "<svg/>")))
    job = wait_job(client, sent.json()["id"])
    assert job["status"] == "succeeded"
    assert _listing(_app_dir(client) / "html") == ["home.html", "img", "img/logo.svg"]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "warning: no index.html at the root" in log


def test_leftovers_of_an_interrupted_replacement_are_swept(client: Any) -> None:
    admin(client)
    site = _site(client)["site"]
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
    job = wait_job(client, _upload(client, site["id"], _zip(("index.html", "i"))).json()["id"])
    assert job["status"] == "succeeded"
    assert sorted(p.name for p in app_dir.iterdir()) == [".hivora-upload-new.zip", "html"]


def test_a_failed_replacement_leaves_the_site_as_it_was(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hivora.core import fs

    admin(client)
    site = _site(client)["site"]
    html = _app_dir(client) / "html"
    before = (html / "index.html").read_text()

    def boom(target: Path, staging: Path, root: Path) -> list[str]:
        raise OSError("disk gone")

    monkeypatch.setattr(fs, "replace_contents", boom)
    job = wait_job(client, _upload(client, site["id"], _zip(("index.html", "new"))).json()["id"])
    assert job["status"] == "failed" and "disk gone" in job["error"]
    assert _listing(html) == ["index.html"] and (html / "index.html").read_text() == before
    assert sorted(p.name for p in _app_dir(client).iterdir()) == ["html"]  # upload, staging


def test_replacement_runs_after_the_deploy_and_the_first_page(client: Any) -> None:
    admin(client)
    created = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8190}).json()
    # Sent at once, without waiting: queued behind the deploy and the first page.
    sent = _upload(client, created["site"]["id"], _zip(("index.html", "mine")))
    assert sent.status_code == 202, sent.text
    jobs = [wait_job(client, j) for j in
            (created["job"]["id"], created["content_job"]["id"], sent.json()["id"])]  # fmt: skip
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
    site = _site(client)["site"]
    body = _zip(("index.html", "i"))
    for app_id in (manual["app"]["id"], 9999):
        r = _upload(client, app_id, body)
        assert r.status_code == 404 and code(r) == "site_not_found"
    assert sorted(p.name for p in _app_dir(client, "manuel").iterdir()) == ["html"]

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        r = _upload(viewer, site["id"], body)
        assert r.status_code == 403 and code(r) == "insufficient_role"
    assert sorted(p.name for p in _app_dir(client).iterdir()) == ["html"]
