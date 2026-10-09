"""The dashboard's update marks: GET /apps says, per app, when a newer version is known
(a newer catalog template; for a free image, what its registry last said), without
asking any registry itself."""

import sqlite3
from typing import Any

from helpers import API, admin, wait_job

from hivora.images.registry import ImageInfo, parse_ref


def updates(client: Any) -> dict[str, Any]:
    return {a["name"]: a["update"] for a in client.get(f"{API}/apps").json()}


def test_a_newer_catalog_template_marks_the_app(client: Any) -> None:
    admin(client)
    for name, port in (("Coffre", 8090), ("Autre", 8091)):
        body = {"template": "vaultwarden", "name": name, "inputs": {"web_port": port}}
        assert wait_job(client, client.post(f"{API}/apps", json=body).json()["job"]["id"])[
            "status"] == "succeeded"  # fmt: skip
    assert updates(client) == {"Coffre": None, "Autre": None}  # up to date

    rt = client.app.state.runtime
    latest = rt.catalog.get("vaultwarden").template.metadata.version
    with sqlite3.connect(rt.settings.db_path) as db:  # deployed from an older version
        db.execute("UPDATE template_version SET version = '0.0.1' WHERE slug = 'vaultwarden'")
    old = {"current": "0.0.1", "latest": latest}
    assert updates(client) == {"Coffre": old, "Autre": old}


def test_a_free_image_is_marked_from_what_its_registry_last_said(client: Any) -> None:
    digests = ["sha256:" + "a" * 64]
    asked: list[str] = []

    class FakeRegistry:
        async def inspect(self, text: str, arch: str) -> ImageInfo:
            asked.append(text)
            return ImageInfo(parse_ref(text), digests[-1], ["amd64", "arm64"], [(80, "tcp")])

    admin(client)
    rt = client.app.state.runtime
    rt.apps.custom.registry = FakeRegistry()
    body = {"name": "Web", "image": "nginx:1.29", "ports": [{"container": 80, "host": 8088}]}
    deployed = client.post(f"{API}/apps/custom", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"

    digests.append("sha256:" + "b" * 64)  # the tag moved on the registry
    rt.apps.custom.inspected.clear()  # nothing known yet
    before = len(asked)
    assert updates(client)["Web"] is None  # never asked: no mark, and no request made
    assert len(asked) == before

    client.portal.call(rt.apps.custom.check_all)  # the background check
    assert updates(client)["Web"] == {"current": "1.29@sha256:aaaaaaaaaaaa",
                                      "latest": "1.29@sha256:bbbbbbbbbbbb"}  # fmt: skip
