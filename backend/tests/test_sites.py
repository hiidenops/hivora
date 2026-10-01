"""The deploy and lifecycle behaviour the static-site manager builds on, pinned before it
exists: a site is an nginx app deployed from the catalog, then started and stopped."""

import time
from itertools import pairwise
from typing import Any

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
