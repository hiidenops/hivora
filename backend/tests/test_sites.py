"""The deploy and lifecycle behaviour the static-site manager builds on, pinned before it
exists: a site is an nginx app deployed from the catalog, then started and stopped."""

from itertools import pairwise
from typing import Any

import yaml
from helpers import API, admin, code, wait_job


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
