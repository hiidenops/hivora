from typing import Any

import yaml
from helpers import API, admin, code, wait_job

from hivora.images.registry import ImageInfo, parse_ref


def compose_of(client: Any, app_id: int) -> dict[str, Any]:
    return yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])


def test_template_upgrade_and_restore(client: Any) -> None:
    import sqlite3

    admin(client)
    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8090}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    assert client.get(f"{API}/apps/{app_id}/upgrade").json()["available"] is False

    # The app was deployed from an older version of the template.
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    with sqlite3.connect(rt.settings.db_path) as db:
        db.execute("UPDATE template_version SET version = '0.0.1' WHERE slug = 'vaultwarden'")
    status = client.get(f"{API}/apps/{app_id}/upgrade").json()
    assert status["available"] is True and status["current"] == "0.0.1"
    assert status["kind"] == "template"
    assert client.post(f"{API}/apps/{app_id}/upgrade/plan").json()["revision"] == 2
    job = client.post(f"{API}/apps/{app_id}/upgrade", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert client.get(f"{API}/apps/{app_id}/upgrade").json()["available"] is False

    # Revision 3 moves the port; restoring revision 1 brings it back as revision 4.
    settings = client.get(f"{API}/apps/{app_id}/settings").json()["values"]
    job = client.put(
        f"{API}/apps/{app_id}/settings", json={"inputs": {**settings, "web_port": 8091}}
    ).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert compose_of(client, app_id)["services"]["server"]["ports"][0]["published"] == "8091"
    revisions = client.get(f"{API}/apps/{app_id}/revisions").json()
    assert [r["restorable"] for r in revisions] == [True, True, True]
    plan = client.post(f"{API}/apps/{app_id}/revisions/1/plan").json()
    assert plan["revision"] == 4 and "8090" in plan["diff"]
    job = client.post(f"{API}/apps/{app_id}/revisions/1/restore", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert compose_of(client, app_id)["services"]["server"]["ports"][0]["published"] == "8090"
    missing = client.post(f"{API}/apps/{app_id}/revisions/99/plan")
    assert missing.status_code == 404


def test_free_image_upgrade_follows_the_registry(client: Any) -> None:
    digests = ["sha256:" + "a" * 64]

    class FakeRegistry:
        async def inspect(self, text: str, arch: str) -> ImageInfo:
            return ImageInfo(parse_ref(text), digests[-1], ["amd64", "arm64"], [(80, "tcp")])

    admin(client)
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    rt.apps.registry = FakeRegistry()
    body = {"name": "Web", "image": "nginx:1.29", "ports": [{"container": 80, "host": 8088}]}
    deployed = client.post(f"{API}/apps/custom", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    assert client.get(f"{API}/apps/{app_id}/upgrade").json() == {
        "kind": "image", "available": False,
        "current": "1.29@sha256:aaaaaaaaaaaa", "latest": "1.29@sha256:aaaaaaaaaaaa",
    }  # fmt: skip

    digests.append("sha256:" + "b" * 64)  # the tag moved
    rt.apps._inspected.clear()
    assert client.get(f"{API}/apps/{app_id}/upgrade").json()["available"] is True
    job = client.post(f"{API}/apps/{app_id}/upgrade", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    image = compose_of(client, app_id)["services"]["app"]["image"]
    assert image == "nginx:1.29@sha256:" + "b" * 64
    assert client.get(f"{API}/apps/{app_id}/upgrade").json()["available"] is False
    # Settings changes now keep the new image; restoring revision 1 pins the old one again.
    job = client.post(f"{API}/apps/{app_id}/revisions/1/restore", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert compose_of(client, app_id)["services"]["app"]["image"].endswith("a" * 64)
    assert code(client.post(f"{API}/apps/{app_id}/revisions/0/plan")) == "not_found"
