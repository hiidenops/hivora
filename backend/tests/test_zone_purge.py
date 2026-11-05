"""A zone removed with everything in it: its apps (data kept unless asked), then the zone."""

from typing import Any

from helpers import API, admin, code, wait_job
from test_links import linked_pair


def _move(client: Any, app_id: int, zone: str) -> None:
    moved = client.put(f"{API}/apps/{app_id}/zone", json={"zone": zone}).json()
    assert wait_job(client, moved["id"])["status"] == "succeeded"


def test_a_zone_is_removed_with_its_apps_data_kept_unless_asked(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    zone = client.post(f"{API}/zones", json={"name": "Labo", "color": "#d97706",
                                             "network_mode": "shared"}).json()  # fmt: skip
    ids = []
    for name, port in (("Alpha", 8481), ("Beta", 8482)):
        body = {
            "template": "nginx",
            "name": name,
            "zone": zone["slug"],
            "inputs": {"web_port": port},
        }
        created = client.post(f"{API}/apps", json=body).json()
        assert wait_job(client, created["job"]["id"])["status"] == "succeeded"
        ids.append(created["app"]["id"])
    data = rt.settings.volumes_root / "alpha"
    data.mkdir(parents=True, exist_ok=True)

    plan = client.get(f"{API}/zones/{zone['slug']}/purge").json()
    assert [a["name"] for a in plan["apps"]] == ["Alpha", "Beta"]
    assert (plan["system"], plan["blocked"], plan["vpn"]) == (False, [], None)
    assert any(str(data) in a["data"] for a in plan["apps"])

    job = client.post(f"{API}/zones/{zone['slug']}/purge", json={}).json()
    assert wait_job(client, job["id"], within=30)["status"] == "succeeded"
    assert [z["slug"] for z in client.get(f"{API}/zones").json()] == ["administration"]
    assert all(client.get(f"{API}/apps/{i}").status_code == 404 for i in ids)
    assert data.exists()  # data kept: not asked
    assert f"hivora-zone-{zone['slug']}" not in [n.name for n in rt.gateway.networks]


def test_administration_and_a_zone_another_zone_needs_are_never_purged(client: Any) -> None:
    db, tool = linked_pair(client)
    client.post(f"{API}/zones", json={"name": "Bases", "color": "#d97706"})
    _move(client, db["id"], "bases")  # the tool stays outside: it needs the database
    plan = client.get(f"{API}/zones/bases/purge").json()
    assert plan["blocked"] == ["Outil"]
    refused = client.post(f"{API}/zones/bases/purge", json={})
    assert (refused.status_code, code(refused)) == (409, "zone_purge_blocked")
    admin_zone = client.post(f"{API}/zones/administration/purge", json={})
    assert (admin_zone.status_code, code(admin_zone)) == (409, "zone_purge_blocked")

    _move(client, tool["id"], "bases")  # both inside: the tool goes first, then the database
    job = client.post(f"{API}/zones/bases/purge", json={"remove_data": True}).json()
    assert wait_job(client, job["id"], within=30)["status"] == "succeeded"
    assert client.get(f"{API}/apps/{db['id']}").status_code == 404
