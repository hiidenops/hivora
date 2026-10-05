"""The ports an nginx host publishes for its added sites (sites.ports), and what every
revision of the host then publishes: the sites as they are now."""

import json
import sqlite3
from typing import Any

import yaml
from helpers import API, admin, code, wait_job

from hivora.templates.overrides import ExtraPort, Overrides, ServiceOverrides


def _host(client: Any) -> int:
    admin(client)
    created = client.post(f"{API}/sites", json={"name": "Vitrine", "port": 8190}).json()
    wait_job(client, created["job"]["id"])
    wait_job(client, created["content_job"]["id"])
    app_id: int = created["site"]["id"]
    return app_id


def _add(client: Any, app_id: int, slug: str, port: int, enabled: bool = True) -> None:
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO site (app_id, slug, name, root, port, enabled, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, '2026-10-05 12:00:00.000000')",
                     (app_id, slug, slug, slug, port, enabled))  # fmt: skip


def _ports(client: Any, slug: str, overrides: Overrides | None = None) -> list[ExtraPort]:
    from hivora.sites.ports import site_ports

    rt = client.app.state.runtime

    async def read() -> list[ExtraPort]:
        async with rt.sessions() as session:
            return await site_ports(session, slug, overrides or Overrides())

    result: list[ExtraPort] = client.portal.call(read)
    return result


def _published(client: Any, app_id: int) -> list[tuple[str, int, str | None]]:
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    ports = compose["services"]["server"]["ports"]
    return [(p["published"], p["target"], p.get("host_ip")) for p in ports]


def _same_settings(client: Any, app_id: int) -> Any:
    values = client.get(f"{API}/apps/{app_id}/settings").json()["values"]
    return client.put(f"{API}/apps/{app_id}/settings", json={"inputs": values})


def test_the_provider_lists_the_added_sites(client: Any) -> None:
    app_id = _host(client)
    assert _ports(client, "vitrine") == []  # only the main site: nothing to add
    _add(client, app_id, "blog", 8096)
    _add(client, app_id, "wiki", 8097, enabled=False)  # off: keeps its port
    assert _ports(client, "vitrine") == [ExtraPort(container=8096, host=8096),
                                         ExtraPort(container=8097, host=8097)]  # fmt: skip
    assert {p.exposure for p in _ports(client, "vitrine")} == {"lan"}

    # The sites follow the main site's exposure (its 80/tcp port).
    public = Overrides(services={"server": ServiceOverrides(publish={"80/tcp": "public"})})
    assert {p.exposure for p in _ports(client, "vitrine", public)} == {"public"}
    hidden = Overrides(services={"server": ServiceOverrides(publish={"80/tcp": "none"})})
    assert _ports(client, "vitrine", hidden) == []

    # A catalog nginx is no host, whatever its rows; an unknown slug neither.
    manual = client.post(f"{API}/apps", json={"template": "nginx", "name": "Manuel",
                                              "inputs": {"web_port": 8180}}).json()  # fmt: skip
    wait_job(client, manual["job"]["id"])
    assert _ports(client, "manuel") == [] and _ports(client, "nope") == []


def test_every_revision_publishes_the_sites_as_they_are_now(client: Any) -> None:
    app_id = _host(client)
    lan = "192.168.1.10"
    assert _published(client, app_id) == [("8190", 80, lan)]  # revision 1: no site yet

    _add(client, app_id, "blog", 8096)
    job = _same_settings(client, app_id).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"  # revision 2
    assert _published(client, app_id) == [("8190", 80, lan), ("8096", 8096, lan)]
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:  # never stored in the revision's advanced settings
        rows = conn.execute("SELECT number, overrides FROM app_revision ORDER BY number").fetchall()
    assert [(n, json.loads(o) if o else None) for n, o in rows] == [(1, None), (2, None)]

    # Restoring revision 1 (from before the site): the site keeps its port.
    job = client.post(f"{API}/apps/{app_id}/revisions/1/restore", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert _published(client, app_id) == [("8190", 80, lan), ("8096", 8096, lan)]

    # A template upgrade too.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE template_version SET version = '1.0.0' WHERE slug = 'nginx'")
    job = client.post(f"{API}/apps/{app_id}/upgrade", json={}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert _published(client, app_id) == [("8190", 80, lan), ("8096", 8096, lan)]

    # The site gone: the next revision no longer publishes its port.
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM site WHERE slug = 'blog'")
    assert wait_job(client, _same_settings(client, app_id).json()["id"])["status"] == "succeeded"
    assert _published(client, app_id) == [("8190", 80, lan)]


def test_a_site_port_taken_elsewhere_is_a_conflict(client: Any) -> None:
    app_id = _host(client)
    other = client.post(f"{API}/apps", json={"template": "nginx", "name": "Autre",
                                             "inputs": {"web_port": 8096}}).json()  # fmt: skip
    wait_job(client, other["job"]["id"])
    _add(client, app_id, "blog", 8096)
    revisions = len(client.get(f"{API}/apps/{app_id}/revisions").json())
    refused = _same_settings(client, app_id)
    assert refused.status_code == 409 and code(refused) == "port_conflict"
    [conflict] = refused.json()["error"]["details"]["conflicts"]
    assert conflict["port"] == 8096 and conflict["used_by"] == "autre"
    assert conflict["suggestion"] not in (None, 8096, 8190)
    assert len(client.get(f"{API}/apps/{app_id}/revisions").json()) == revisions  # nothing made
