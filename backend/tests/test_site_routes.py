"""Routes of the sites an nginx hosts (/apps/{app_id}/sites): the app -> sites model."""

import sqlite3
from typing import Any

from helpers import API, STRONG, admin, code, login, nginx_host, other_user, wait_job

LAN = "192.168.1.10"  # the test settings' host LAN address


def _host(client: Any) -> int:
    admin(client)
    return nginx_host(client, running=True)


def _state(client: Any) -> tuple[Any, ...]:
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        return (
            conn.execute("SELECT * FROM site ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM app_revision ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM job ORDER BY id").fetchall(),
        )


def _sites(client: Any, app_id: int) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = client.get(f"{API}/apps/{app_id}/sites").json()["sites"]
    return sites


def test_a_host_and_its_sites(client: Any) -> None:
    app_id = _host(client)
    host = client.get(f"{API}/apps/{app_id}/sites").json()
    assert {k: v for k, v in host.items() if k != "sites"} == {
        "app_id": app_id, "slug": "vitrine", "name": "Vitrine", "upgrade_required": False,
        "stopped": False, "max_sites": 30, "config": None,
    }  # fmt: skip
    [main] = host["sites"]
    assert {k: v for k, v in main.items() if k != "id"} == {
        "slug": "main", "name": "Vitrine", "main": True, "port": 8190, "server_name": None,
        "enabled": True, "url": f"http://{LAN}:8190",
    }  # fmt: skip
    missing = client.get(f"{API}/apps/9999/sites")
    assert missing.status_code == 404 and code(missing) == "site_not_found"


def test_add_a_site_after_its_plan(client: Any) -> None:
    app_id = _host(client)
    before = _state(client)
    body = {"name": "Blog", "port": 8096, "server_name": "blog.example.com"}
    plan = client.post(f"{API}/apps/{app_id}/sites/plan", json=body)
    assert plan.status_code == 200, plan.text
    assert {k: v for k, v in plan.json().items() if k != "diff"} == {
        "recreate": True, "revision": 2, "ports_before": [], "ports_after": [8096],
    }  # fmt: skip
    assert "published: '8096'" in plan.json()["diff"] and _state(client) == before

    added = client.post(f"{API}/apps/{app_id}/sites", json=body)
    assert added.status_code == 202, added.text
    out = added.json()
    assert out["site"]["slug"] == "blog" and out["site"]["url"] == f"http://{LAN}:8096"
    assert (out["job"]["kind"], out["config_job"]["kind"]) == ("update", "site_config")
    assert out["job"]["id"] < out["config_job"]["id"]
    assert wait_job(client, out["config_job"]["id"])["status"] == "succeeded"
    assert [s["slug"] for s in _sites(client, app_id)] == ["main", "blog"]


def test_errors_and_their_status(client: Any) -> None:
    app_id = _host(client)
    other = client.post(f"{API}/apps", json={"template": "nginx", "name": "Autre",
                                             "inputs": {"web_port": 8097}}).json()  # fmt: skip
    wait_job(client, other["job"]["id"])
    blog = client.post(f"{API}/apps/{app_id}/sites", json={"name": "Blog", "port": 8096}).json()
    wait_job(client, blog["config_job"]["id"])
    main_id = _sites(client, app_id)[0]["id"]
    before = _state(client)
    cases = [
        ("post", "sites", {"name": "x", "port": 80}, 422, "invalid_site_config"),
        ("post", "sites", {"name": "x", "port": 8097}, 409, "port_conflict"),
        ("post", "sites/plan", {"name": "x", "port": 8190}, 409, "port_conflict"),
        ("post", "sites", {"name": "Blog", "port": 8098}, 409, "site_exists"),
        ("post", "sites", {"name": "x", "port": 0}, 422, "request_invalid"),
        ("put", f"sites/{main_id}/port", {"port": 8096}, 409, "port_conflict"),  # the blog's
        ("put", f"sites/{main_id}/server-name", {"server_name": "a.com"}, 409, "main_site_fixed"),
        ("put", f"sites/{blog['site']['id']}/server-name", {"server_name": "a;b"}, 422,
         "invalid_site_config"),
        ("put", "sites/9999/enabled", {"enabled": False}, 404, "site_not_found"),
        ("delete", f"sites/{main_id}", None, 409, "main_site_fixed"),
    ]  # fmt: skip
    for method, path, body, status, error in cases:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(f"{API}/apps/{app_id}/{path}", **kwargs)
        assert (r.status_code, code(r)) == (status, error), (path, r.text)
    assert _state(client) == before  # none of them wrote anything


def test_port_toggle_name_and_removal(client: Any) -> None:
    app_id = _host(client)
    added = client.post(f"{API}/apps/{app_id}/sites", json={"name": "Blog", "port": 8096}).json()
    wait_job(client, added["config_job"]["id"])
    site = added["site"]["id"]
    base = f"{API}/apps/{app_id}/sites/{site}"

    off = client.put(f"{base}/enabled", json={"enabled": False})
    assert off.status_code == 202 and off.json()["kind"] == "site_config"
    wait_job(client, off.json()["id"])
    named = client.put(f"{base}/server-name", json={"server_name": "blog.example.com"})
    assert (
        named.status_code == 202 and wait_job(client, named.json()["id"])["status"] == "succeeded"
    )
    [_, blog] = _sites(client, app_id)
    assert (blog["enabled"], blog["server_name"]) == (False, "blog.example.com")

    plan = client.post(f"{base}/port/plan", json={"port": 8099}).json()
    assert plan["recreate"] and plan["ports_after"] == [8099]
    moved = client.put(f"{base}/port", json={"port": 8099})
    assert moved.status_code == 202 and moved.json()["site"]["port"] == 8099
    assert moved.json()["job"]["kind"] == "update"
    wait_job(client, moved.json()["config_job"]["id"])

    removal = client.get(f"{base}/removal-plan").json()
    assert removal["recreate"] and removal["ports_after"] == []
    gone = client.delete(base, params={"remove_data": "true"})
    assert gone.status_code == 202 and gone.json()["site"] is None
    assert gone.json()["config_job"]["id"] < gone.json()["job"]["id"]  # unconfigured first
    wait_job(client, gone.json()["job"]["id"])
    assert [s["slug"] for s in _sites(client, app_id)] == ["main"]


def test_a_catalog_nginx_starts_hosting(client: Any) -> None:
    admin(client)
    manual = client.post(f"{API}/apps", json={"template": "nginx", "name": "Manuel",
                                              "inputs": {"web_port": 8180}}).json()  # fmt: skip
    wait_job(client, manual["job"]["id"])
    app_id = manual["app"]["id"]
    assert code(client.get(f"{API}/apps/{app_id}/sites")) == "site_not_found"  # not a host yet
    hosted = client.post(f"{API}/apps/{app_id}/sites/hosting")
    assert hosted.status_code == 200, hosted.text
    assert [(s["slug"], s["main"], s["port"]) for s in hosted.json()["sites"]] == [
        ("main", True, 8180)
    ]
    again = client.post(f"{API}/apps/{app_id}/sites/hosting").json()  # no change
    assert [s["id"] for s in again["sites"]] == [s["id"] for s in hosted.json()["sites"]]

    vw = client.post(f"{API}/apps", json={"template": "vaultwarden", "name": "vw"}).json()
    wait_job(client, vw["job"]["id"])
    refused = client.post(f"{API}/apps/{vw['app']['id']}/sites/hosting")
    assert refused.status_code == 409 and code(refused) == "not_a_nginx_app"


def test_an_old_host_and_a_stopped_one(client: Any) -> None:
    app_id = _host(client)
    stop = client.post(f"{API}/apps/{app_id}/stop").json()
    wait_job(client, stop["id"])
    assert client.get(f"{API}/apps/{app_id}/sites").json()["stopped"] is True
    r = client.post(f"{API}/apps/{app_id}/sites", json={"name": "Blog", "port": 8096})
    assert r.status_code == 409 and code(r) == "site_host_stopped"

    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:  # as an nginx deployed from template 1.0.0
        conn.execute("DELETE FROM volume_mount WHERE target = '/etc/nginx/hivora.d'")
    assert client.get(f"{API}/apps/{app_id}/sites").json()["upgrade_required"] is True


def test_viewers_read_operators_write(client: Any) -> None:
    app_id = _host(client)
    main_id = _sites(client, app_id)[0]["id"]
    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{API}/apps/{app_id}/sites").status_code == 200
        writes = [
            ("post", "sites/hosting", None), ("post", "sites/config", None),
            ("post", "sites/plan", {"name": "b", "port": 8096}),
            ("post", "sites", {"name": "b", "port": 8096}),
            ("put", f"sites/{main_id}/enabled", {"enabled": False}),
            ("put", f"sites/{main_id}/server-name", {"server_name": None}),
            ("post", f"sites/{main_id}/port/plan", {"port": 8096}),
            ("put", f"sites/{main_id}/port", {"port": 8096}),
            ("get", f"sites/{main_id}/removal-plan", None), ("delete", f"sites/{main_id}", None),
        ]  # fmt: skip
        for method, path, body in writes:
            kwargs = {"json": body} if body is not None else {}
            r = getattr(viewer, method)(f"{API}/apps/{app_id}/{path}", **kwargs)
            assert (r.status_code, code(r)) == (403, "insufficient_role"), path
