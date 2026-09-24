"""HTTP API: authentication, roles, CSRF, users, deploy flow, WebSocket, audit."""

import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from helpers import API, STRONG, admin, code, login, other_user, wait_job

from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime

FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        volumes_root=tmp_path / "srv",
        catalog_dir=Path(__file__).parents[2] / "templates",
        dev_insecure_cookies=True,
        puid=os.getuid(),
        pgid=os.getgid(),
    )
    runtime = Runtime.build(
        settings,
        gateway=FakeDockerGateway(),
        compose_cmd=FAKE,
        compose_env={"FAKE_COMPOSE_MODE": "leak"},
    )
    with TestClient(create_app(runtime=runtime)) as c:
        yield c


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
    with client.websocket_connect("/ws") as ws:  # consoles need a fresh TOTP (15 min)
        ws.send_json({"op": "console.open", "id": "x", "app": 1, "kind": "shell"})
        assert ws.receive_json()["code"] == "totp_required"
        ws.send_json(
            {
                "op": "console.open",
                "id": "x",
                "app": 1,
                "kind": "shell",
                "totp_code": pyotp.TOTP(secret).now(),
            }
        )
        assert ws.receive_json()["code"] == "app_not_found"  # past the TOTP gate

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

    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8090}}
    plan = client.post(f"{API}/apps/plan", json=body).json()
    assert plan["slug"] == "coffre" and "${HV_SECRET_ADMIN_TOKEN}" in plan["compose_yaml"]
    invalid = client.post(f"{API}/apps/plan", json={**body, "inputs": {"web_port": 0}})
    assert invalid.status_code == 422 and invalid.json()["error"]["details"]["fields"] == {
        "web_port": "out_of_range"
    }

    assert isinstance(client.get(f"{API}/metrics/host").json(), list)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "channel": "state"})
        assert ws.receive_json() == {"channel": "state", "type": "snapshot", "apps": {}}
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
