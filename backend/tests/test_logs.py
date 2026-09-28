import time
from typing import Any

from helpers import API, admin, wait_job

from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.realtime.logs import split_timestamp, unix

SECRET = "supersecret-token-123"


def test_split_timestamp() -> None:
    assert split_timestamp("2026-09-28T10:00:01.5Z hello world") == (
        "2026-09-28T10:00:01.5Z", "hello world"
    )  # fmt: skip
    assert split_timestamp("no time here") == (None, "no time here")
    assert unix("2026-09-28T10:00:01.123456789Z") == 1790589601


def test_live_logs_and_download(client: Any) -> None:
    admin(client)
    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"admin_token": SECRET}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]

    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    gw = runtime.gateway
    gw.logs_by_container["v1"] = [
        "2026-09-28T10:00:02.000000000Z second",
        f"2026-09-28T10:00:03.000000000Z token is {SECRET}",
    ]
    gw.logs_by_container["db1"] = ["2026-09-28T10:00:01.000000000Z first (db)"]
    for cid, svc in (("v1", "server"), ("db1", "db")):
        gw.put(ContainerInfo(
            id=cid, name=f"coffre-{svc}-1", image="x", state=ContainerState.RUNNING,
            labels={"io.hivora.app": "coffre", "com.docker.compose.service": svc},
        ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while len([c for c in runtime.state.store.containers() if c.id in ("v1", "db1")]) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.02)

    text = client.get(f"{API}/apps/{app_id}/logs").text
    assert text.splitlines() == [
        "2026-09-28T10:00:01.000000000Z [db] first (db)",
        "2026-09-28T10:00:02.000000000Z [server] second",
        "2026-09-28T10:00:03.000000000Z [server] token is ••••••",
    ]
    only = client.get(f"{API}/apps/{app_id}/logs", params={"service": "db"}).text
    assert only.count("\n") == 1 and "[db]" in only

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "logs.open", "id": "l1", "app": app_id})
        opened = ws.receive_json()
        assert opened["type"] == "opened" and opened["services"] == ["db", "server"]
        seen: list[dict[str, Any]] = []
        while len(seen) < 3:
            msg = ws.receive_json()
            assert msg["channel"] == "logs" and msg["type"] == "lines"
            seen += msg["lines"]
        texts = sorted(line["l"] for line in seen)
        assert texts == ["first (db)", "second", "token is ••••••"]
        assert {line["s"] for line in seen} == {"db", "server"}
        ws.send_json({"op": "logs.close", "id": "l1"})

    time.sleep(0.8)  # the audit recorder writes in batches
    actions = [a["action"] for a in client.get(f"{API}/audit").json()]
    assert "app.logs_downloaded" in actions
