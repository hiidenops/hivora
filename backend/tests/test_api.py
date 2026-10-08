"""HTTP API: authentication, roles, CSRF, users, deploy flow, WebSocket, audit."""

import time
from pathlib import Path
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from helpers import API, STRONG, admin, code, login, other_user, wait_job


def test_initial_admin_must_change_password(client: TestClient) -> None:
    me = login(client, "admin", "admin")
    assert me["must_change_password"] is True
    r = client.get(f"{API}/apps")
    assert r.status_code == 403 and code(r) == "password_change_required"

    no_csrf = client.post(
        f"{API}/auth/password",
        json={"current": "admin", "new": STRONG},
        headers={"X-CSRF-Token": "nope"},
    )
    assert no_csrf.status_code == 403 and code(no_csrf) == "csrf_failed"
    weak = client.post(f"{API}/auth/password", json={"current": "admin", "new": "admin"})
    assert weak.status_code == 422 and code(weak) == "weak_password"

    assert (
        client.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG}).status_code
        == 204
    )
    assert client.get(f"{API}/auth/me").json()["must_change_password"] is False
    assert client.get(f"{API}/apps").status_code == 200


def test_unauthenticated_and_rate_limited(client: TestClient) -> None:
    assert code(client.get(f"{API}/apps")) == "not_authenticated"
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "bad"})
        assert r.status_code == 401 and code(r) == "invalid_credentials"
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_roles_and_user_management(client: TestClient) -> None:
    admin(client)
    for name, role in (("olive", "operator"), ("victor", "viewer")):
        r = client.post(
            f"{API}/users", json={"username": name, "role": role, "password": "temporary-pass-1"}
        )
        assert r.status_code == 201 and r.json()["must_change_password"] is True
    users = {u["username"]: u for u in client.get(f"{API}/users").json()}
    assert set(users) == {"admin", "olive", "victor"}

    # The last active admin can neither be demoted nor disabled, nor delete itself.
    me = users["admin"]["id"]
    assert code(client.patch(f"{API}/users/{me}", json={"role": "viewer"})) == "last_admin"
    assert code(client.patch(f"{API}/users/{me}", json={"disabled": True})) == "last_admin"
    assert client.delete(f"{API}/users/{me}").status_code == 409

    plan = {"template": "vaultwarden", "name": "vw"}
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{API}/apps").status_code == 200
        r = viewer.post(f"{API}/apps/plan", json=plan)
        assert r.status_code == 403 and code(r) == "insufficient_role"
        viewer_cookies = dict(viewer.cookies)

    # Disabling a user kills its sessions immediately.
    client.patch(f"{API}/users/{users['victor']['id']}", json={"disabled": True})
    with other_user(client) as viewer:
        viewer.cookies.update(viewer_cookies)
        assert viewer.get(f"{API}/apps").status_code == 401

    with other_user(client) as operator:
        login(operator, "olive", "temporary-pass-1")
        operator.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert operator.post(f"{API}/apps/plan", json=plan).status_code == 200
        assert code(operator.get(f"{API}/users")) == "insufficient_role"

    assert (
        client.post(
            f"{API}/users/{users['olive']['id']}/password", json={"temporary": "another-temp-1"}
        ).status_code
        == 204
    )
    assert client.delete(f"{API}/users/{users['olive']['id']}").status_code == 204


def test_totp_and_recovery_codes(client: TestClient) -> None:
    admin(client)
    secret = client.post(f"{API}/auth/totp/enroll").json()["secret"]
    bad = client.post(f"{API}/auth/totp/confirm", json={"code": "000000"})
    assert bad.status_code == 401
    codes = client.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}).json()[
        "recovery_codes"
    ]
    assert len(codes) == 10
    auth = client.app.state.runtime.auth  # type: ignore[attr-defined]
    with client.websocket_connect("/ws") as ws:  # consoles need a fresh TOTP (15 min)
        ws.send_json({"op": "console.open", "id": "x", "app": 1, "kind": "shell"})
        assert ws.receive_json()["code"] == "totp_required"
        opening = {"op": "console.open", "id": "x", "app": 1, "kind": "shell",
                   "totp_code": pyotp.TOTP(secret).now()}  # fmt: skip
        ws.send_json(opening)  # the code that just confirmed the enrollment: used
        assert ws.receive_json()["code"] == "invalid_credentials"
        auth.totp._used.clear()  # as if the next 30 s step had come
        ws.send_json(opening)
        assert ws.receive_json()["code"] == "app_not_found"  # past the TOTP gate
    auth.totp._used.clear()

    with other_user(client) as other:
        r = other.post(f"{API}/auth/login", json={"username": "admin", "password": STRONG})
        assert r.status_code == 401 and code(r) == "totp_required"
        login(other, "admin", STRONG, totp_code=pyotp.TOTP(secret).now())
    with other_user(client) as other:
        login(other, "admin", STRONG, totp_code=codes[0])
        again = other.post(
            f"{API}/auth/login",
            json={"username": "admin", "password": STRONG, "totp_code": codes[0]},
        )
        assert again.status_code == 401  # recovery codes are single-use


def test_deploy_flow_websocket_and_audit(client: TestClient) -> None:
    admin(client)
    templates = {t["slug"]: t for t in client.get(f"{API}/templates").json()}
    assert templates["vaultwarden"]["compatible"] is True
    detail = client.get(f"{API}/templates/minecraft").json()
    assert detail["form"]["basic"][0]["id"] == "eula"
    wg = client.get(f"{API}/templates/wireguard").json()["form"]["basic"][0]
    assert wg["default"] == "203.0.113.7"  # host facts pre-filled in the form

    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8090}}
    plan = client.post(f"{API}/apps/plan", json=body).json()
    assert plan["slug"] == "coffre" and "${HV_SECRET_ADMIN_TOKEN:-}" in plan["compose_yaml"]
    invalid = client.post(f"{API}/apps/plan", json={**body, "inputs": {"web_port": 0}})
    assert invalid.status_code == 422 and invalid.json()["error"]["details"]["fields"] == {
        "web_port": "out_of_range"
    }

    assert isinstance(client.get(f"{API}/metrics/host").json(), list)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "channel": "state"})
        assert ws.receive_json() == {"channel": "state", "type": "snapshot", "apps": {}}
        ws.send_json({"op": "subscribe", "channel": "app_metrics", "app": "coffre"})
        assert ws.receive_json() == {
            "channel": "app_metrics", "app": "coffre", "type": "snapshot", "samples": []
        }  # fmt: skip
        ws.send_json({"op": "subscribe", "channel": "jobs"})
        deployed = client.post(f"{API}/apps", json=body)
        assert deployed.status_code == 202
        job_id = deployed.json()["job"]["id"]
        seen: list[dict[str, Any]] = []
        while not seen or seen[-1]["type"] != "finished":
            seen.append(ws.receive_json())
        assert seen[-1] == {
            "channel": "jobs",
            "type": "finished",
            "id": job_id,
            "status": "succeeded",
            "error": None,
            "app": "coffre",
        }

    job = wait_job(client, job_id)
    assert job["status"] == "succeeded" and "••••••" in job["log"]
    [app] = client.get(f"{API}/apps").json()
    # The fake gateway runs no container: intent says running, reality is missing.
    assert app["status"] == "missing" and app["drift"] is True
    assert client.get(f"{API}/apps/{app['id']}/revisions").json()[0]["status"] == "applied"

    stop = client.post(f"{API}/apps/{app['id']}/stop").json()
    assert wait_job(client, stop["id"])["status"] == "succeeded"
    assert client.get(f"{API}/apps/{app['id']}").json()["drift"] is False

    plan_rm = client.get(f"{API}/apps/{app['id']}/removal-plan").json()
    assert plan_rm["data"] and plan_rm["files"]
    rm = client.delete(f"{API}/apps/{app['id']}").json()
    assert wait_job(client, rm["id"])["status"] == "succeeded"
    assert client.get(f"{API}/apps").json() == []

    time.sleep(0.8)  # the audit recorder writes in small batches
    actions = [(a["action"], a["username"]) for a in client.get(f"{API}/audit").json()]
    assert ("auth.login", "admin") in actions
    assert ("app.created", "admin") in actions
    assert any(a == "job.finished" for a, _ in actions)


def test_websocket_rejects_anonymous_and_cross_origin(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws") as ws:
        ws.receive_json()
    admin(client)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()


def test_clear_jobs_and_audit(client: TestClient) -> None:
    admin(client)
    body = {"template": "vaultwarden", "name": "vw"}
    job = client.post(f"{API}/apps", json=body).json()["job"]
    wait_job(client, job["id"])
    assert client.delete(f"{API}/jobs").json() == {"deleted": 1}
    assert client.get(f"{API}/jobs").json() == []

    time.sleep(0.8)  # let the recorder flush
    assert client.delete(f"{API}/audit").json()["deleted"] > 0
    [entry] = client.get(f"{API}/audit").json()
    assert (entry["action"], entry["username"]) == ("audit.cleared", "admin")


def test_console_over_websocket(client: TestClient) -> None:
    from hivora.docker_gateway import ContainerInfo, ContainerState

    admin(client)
    body = {"template": "minecraft", "name": "cube", "inputs": {"eula": True}}
    deployed = client.post(f"{API}/apps", json=body).json()
    wait_job(client, deployed["job"]["id"])
    app_id = deployed["app"]["id"]
    detail = client.get(f"{API}/apps/{app_id}").json()
    assert detail["console"]["server"] is True and detail["console"]["commands"]

    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    runtime.gateway.put(ContainerInfo(
        id="c1", name="cube-server-1", image="mc", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "cube", "com.docker.compose.service": "server"},
    ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while runtime.state.store.app("cube").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)

    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "op": "console.open",
                "id": "t1",
                "app": app_id,
                "kind": "server",
                "rows": 30,
                "cols": 100,
            }
        )
        assert ws.receive_json()["type"] == "opened"
        assert "rcon-cli" in ws.receive_json()["data"]  # the fake echoes its command first
        ws.send_json({"op": "console.input", "id": "t1", "data": "list\r"})
        assert ws.receive_json() == {
            "channel": "console",
            "id": "t1",
            "type": "data",
            "data": "list\r",
        }
        ws.send_json({"op": "console.close", "id": "t1"})
    [session] = runtime.gateway.execs
    assert session.cmd == ["rcon-cli"] and session.size == (30, 100)

    time.sleep(0.8)
    actions = [a["action"] for a in client.get(f"{API}/audit").json()]
    assert "console.opened" in actions and "console.closed" in actions
    assert runtime.consoles.open_count == 0


def test_curseforge_key_setting_and_fallback(client: TestClient) -> None:
    admin(client)
    assert client.get(f"{API}/system/integrations").json()["curseforge_api_key_set"] is False
    body = {
        "template": "minecraft",
        "name": "atm",
        "inputs": {"eula": True, "server_type": "AUTO_CURSEFORGE", "cf_modpack": "all-the-mods-9"},
    }
    missing = client.post(f"{API}/apps/plan", json=body)
    assert missing.json()["error"]["details"]["fields"] == {"cf_api_key": "required"}

    assert (
        client.put(f"{API}/system/integrations/curseforge", json={"key": "$2a$10$abc"}).status_code
        == 204
    )
    assert client.get(f"{API}/system/integrations").json()["curseforge_api_key_set"] is True
    plan = client.post(f"{API}/apps/plan", json=body)
    assert plan.status_code == 200 and "$2a$10$abc" not in plan.text  # used, never shown
    time.sleep(0.8)
    entry = next(
        a for a in client.get(f"{API}/audit").json() if a["action"] == "settings.secret_updated"
    )
    assert "$2a$10$abc" not in str(entry)


def test_minecraft_players_whitelist_and_ops(client: TestClient) -> None:
    import json

    from hivora.docker_gateway import ContainerInfo, ContainerState

    admin(client)
    body = {"template": "minecraft", "name": "cube", "inputs": {"eula": True}}
    deployed = client.post(f"{API}/apps", json=body).json()
    wait_job(client, deployed["job"]["id"])
    app_id = deployed["app"]["id"]
    detail = client.get(f"{API}/apps/{app_id}").json()
    caps = ("players", "lists", "worlds", "world_import", "world_activate")
    assert detail["game"] == dict.fromkeys(caps, True)
    assert detail["started_at"] is None  # not running
    assert detail["summary"][0] == {"label": {"fr": "Type de serveur", "en": "Server type"},
                                    "value": "Vanilla"}  # fmt: skip
    assert detail["access"] == {"game": "203.0.113.7:25565", "game_lan": "192.168.1.10:25565"}

    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    gw = runtime.gateway
    # Stopped: players unknown, commands refused.
    assert client.get(f"{API}/apps/{app_id}/game/players").json()["running"] is False
    refused = client.post(f"{API}/apps/{app_id}/game/lists/whitelist", json={"name": "Steve"})
    assert refused.status_code == 409 and code(refused) == "server_not_running"

    gw.put(ContainerInfo(
        id="mc1", name="cube-server-1", image="mc", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "cube", "com.docker.compose.service": "server"},
    ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while runtime.state.store.app("cube").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    gw.exec_results["rcon-cli list"] = (0, "There are 1 of a max of 10 players online: Steve")
    gw.exec_results["rcon-cli whitelist add Steve"] = (0, "Added Steve to the whitelist")
    gw.exec_results["rcon-cli op Ghost"] = (0, "That player does not exist")
    assert client.get(f"{API}/apps/{app_id}/game/players").json() == {
        "running": True, "online": 1, "max": 10, "names": ["Steve"],
    }  # fmt: skip
    added = client.post(f"{API}/apps/{app_id}/game/lists/whitelist", json={"name": "Steve"})
    assert added.json() == {"output": "Added Steve to the whitelist"}
    bad = client.post(f"{API}/apps/{app_id}/game/lists/whitelist", json={"name": "Steve; stop"})
    assert bad.status_code == 422
    ghost = client.post(f"{API}/apps/{app_id}/game/lists/ops", json={"name": "Ghost"})
    assert ghost.status_code == 502 and code(ghost) == "game_command_failed"
    assert ["rcon-cli", "whitelist", "add", "Steve"] in gw.exec_calls

    data = Path(runtime.settings.volumes_root) / "cube" / "data"
    (data / "whitelist.json").write_text(json.dumps([{"uuid": "u", "name": "Steve"}]))
    (data / "ops.json").write_text(json.dumps([{"uuid": "v", "name": "Alex", "level": 4}]))
    lists = client.get(f"{API}/apps/{app_id}/game/lists").json()
    assert lists["running"] is True
    wl, ops = lists["lists"]
    assert (wl["id"], wl["enabled"], wl["entries"]) == (
        "whitelist",
        False,
        [{"name": "Steve", "extra": None}],
    )
    assert (ops["id"], ops["enabled"], ops["entries"]) == (
        "ops",
        None,
        [{"name": "Alex", "extra": "4"}],
    )

    job = client.put(
        f"{API}/apps/{app_id}/game/lists/whitelist/enabled", json={"enabled": True}
    ).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert client.get(f"{API}/apps/{app_id}/game/lists").json()["lists"][0]["enabled"] is True
    compose = client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"]
    assert "ENABLE_WHITELIST: 'true'" in compose

    # Worlds: import a .zip, list, download, switch, delete.
    import io
    import zipfile

    (data / "world").mkdir()
    (data / "world" / "level.dat").write_bytes(b"L")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Skyblock/level.dat", b"S")
        zf.writestr("Skyblock/region/r.0.0.mca", b"R" * 10)
    url = f"{API}/apps/{app_id}/game/worlds"
    job = client.post(url, params={"name": "skyblock", "filename": "Skyblock.zip"},
                      content=buf.getvalue())  # fmt: skip
    assert job.status_code == 202 and job.json()["kind"] == "world_import"
    assert wait_job(client, job.json()["id"])["status"] == "succeeded"
    assert not list((data.parent).glob(".hivora-upload-*"))  # upload removed
    listed = client.get(url).json()
    assert listed["active"] == "world"
    assert [(x["name"], x["active"]) for x in listed["worlds"]] == [
        ("world", True), ("skyblock", False),
    ]  # fmt: skip
    again = client.post(url, params={"name": "skyblock"}, content=buf.getvalue())
    assert again.status_code == 409 and code(again) == "world_exists"
    bad = client.post(url, params={"name": "junk"}, content=b"not a zip")
    assert wait_job(client, bad.json()["id"])["status"] == "failed"
    assert not (data / "junk").exists()

    gw.exec_results["rcon-cli save-all flush"] = (0, "Saved the game")
    got = client.get(f"{url}/world/download")
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(got.content)).namelist() == ["world/level.dat"]
    assert ["rcon-cli", "save-all", "flush"] in gw.exec_calls

    refused = client.delete(f"{url}/world")
    assert refused.status_code == 409 and code(refused) == "world_active"
    switched = client.put(f"{url}/active", json={"name": "skyblock"}).json()
    assert wait_job(client, switched["id"])["status"] == "succeeded"
    assert "LEVEL: skyblock" in client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"]
    assert client.get(url).json()["active"] == "skyblock"
    deleted = client.delete(f"{url}/world").json()
    assert wait_job(client, deleted["id"])["status"] == "succeeded"
    assert not (data / "world").exists()
    assert client.delete(f"{url}/nope").status_code == 404


def test_public_address_override(client: TestClient) -> None:
    admin(client)
    bad = client.put(f"{API}/system/integrations/public-address", json={"address": "not a host!"})
    assert bad.status_code == 422
    ok = client.put(f"{API}/system/integrations/public-address", json={"address": "MC.Example.org"})
    assert ok.status_code == 204
    info = client.get(f"{API}/system/integrations").json()
    assert info["public_address"] == "mc.example.org"
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    assert runtime.public_address.current() == "mc.example.org"  # manual wins over the env IP
    client.put(f"{API}/system/integrations/public-address", json={"address": ""})
    assert runtime.public_address.current() == "203.0.113.7"


def test_health_says_first_start_until_admin_changes_password(client: TestClient) -> None:
    health = client.get(f"{API}/system/health").json()
    assert health["status"] == "ok" and health["first_start"] is True
    admin(client)  # admin/admin, then the forced password change
    assert client.get(f"{API}/system/health").json()["first_start"] is False


def test_zones_share_a_network_and_apps_move_between_them(client: TestClient) -> None:
    import yaml

    admin(client)
    gw = client.app.state.runtime.gateway  # type: ignore[attr-defined]
    bad = client.post(f"{API}/zones", json={"name": "Jeux", "color": "red"})
    assert bad.status_code == 422
    zone = client.post(f"{API}/zones", json={"name": "Jeux entre amis", "color": "#d97706",
                                             "network_mode": "shared"}).json()  # fmt: skip
    assert zone["slug"] == "jeux-entre-amis" and zone["apps"] == 0

    body = {"template": "vaultwarden", "name": "vw", "zone": zone["slug"]}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    assert compose["networks"]["zone"] == {"name": "hivora-zone-jeux-entre-amis", "external": True}
    assert compose["services"]["server"]["networks"] == ["default", "zone"]
    assert "hivora-zone-jeux-entre-amis" in [n.name for n in gw.networks]

    refused = client.delete(f"{API}/zones/{zone['slug']}")
    assert refused.status_code == 409 and code(refused) == "zone_not_empty"
    assert client.get(f"{API}/zones").json()[-1]["apps"] == 1

    moved = client.put(f"{API}/apps/{app_id}/zone", json={"zone": None}).json()
    assert wait_job(client, moved["id"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    assert "networks" not in compose
    assert client.delete(f"{API}/zones/{zone['slug']}").status_code == 204
    assert "hivora-zone-jeux-entre-amis" not in [n.name for n in gw.networks]
    admin_zone = client.delete(f"{API}/zones/administration")
    assert admin_zone.status_code == 409


def test_free_image_deploys_like_a_template_app(client: TestClient) -> None:
    import yaml

    from hivora.images.registry import ImageInfo, parse_ref
    from hivora.templates.catalog import host_arch

    class FakeRegistry:
        async def inspect(self, text: str, arch: str) -> ImageInfo:
            ref = parse_ref(text)
            archs = ["riscv64"] if "odd" in text else ["amd64", "arm64"]
            env = {"GF_PATHS_DATA": "/var/lib/grafana"}
            return ImageInfo(
                ref, "sha256:" + "a" * 64, archs, [(3000, "tcp")], [env["GF_PATHS_DATA"]], env
            )

    admin(client)
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    rt.apps.registry = FakeRegistry()
    seen = client.get(f"{API}/apps/images/inspect", params={"ref": "grafana/grafana:12.2.0"}).json()
    assert seen["name"] == "grafana/grafana" and seen["compatible"] is True
    assert seen["ports"][0]["container"] == 3000 and seen["volumes"] == ["/var/lib/grafana"]

    body = {
        "name": "Grafana", "image": "grafana/grafana:12.2.0",
        "ports": [{"container": 3000, "host": 3300, "web": True}],
        "volumes": ["/var/lib/grafana"],
        "env": [{"key": "GF_SECURITY_ADMIN_PASSWORD", "value": "s3cret-pass", "secret": True},
                {"key": "GF_LOG_LEVEL", "value": "warn"}],
    }  # fmt: skip
    assert client.post(f"{API}/apps/custom/plan", json=body).status_code == 200
    deployed = client.post(f"{API}/apps/custom", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    svc = compose["services"]["app"]
    assert svc["image"] == "grafana/grafana:12.2.0@sha256:" + "a" * 64
    assert svc["environment"]["GF_LOG_LEVEL"] == "warn"
    assert svc["environment"]["GF_SECURITY_ADMIN_PASSWORD"].startswith("${HV_SECRET_")
    assert "s3cret-pass" not in yaml.safe_dump(compose)
    assert client.get(f"{API}/apps/{app_id}").json()["access"]["web"].endswith(":3300")

    # Editable later, like any app; and found again after a restart.
    settings = client.get(f"{API}/apps/{app_id}/settings").json()
    assert settings["values"]["port_0"] == 3300
    rt.catalog._custom.clear()
    import asyncio

    asyncio.run(rt.apps.load_custom_templates())
    assert client.get(f"{API}/apps/{app_id}/settings").status_code == 200

    odd = client.post(f"{API}/apps/custom", json={**body, "name": "Odd", "image": "odd/image"})
    assert odd.status_code == 422 and code(odd) == "unsupported_architecture"
    bad = client.post(f"{API}/apps/custom", json={**body, "name": "Bad", "volumes": ["../etc"]})
    assert bad.status_code == 422
    assert host_arch() in ("amd64", "arm64")
