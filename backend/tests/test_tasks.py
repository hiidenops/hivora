import sqlite3
import time
from typing import Any

from helpers import API, admin, code, wait_job

from hivora.docker_gateway import ContainerInfo, ContainerState


def task_row(client: Any, app_id: int, task_id: int) -> Any:
    tasks = client.get(f"{API}/apps/{app_id}/tasks").json()["tasks"]
    return next(t for t in tasks if t["id"] == task_id)


def test_scheduled_tasks(client: Any) -> None:
    admin(client)
    body = {"template": "minecraft", "name": "cube", "inputs": {"eula": True}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    rt = client.app.state.runtime
    gw = rt.gateway

    # Validation: a command needs text; console mode needs a game console (Minecraft has one).
    missing = client.post(f"{API}/apps/{app_id}/tasks", json={"name": "x", "action": "command"})
    assert missing.status_code == 422

    say = {"name": "Prévenir les joueurs", "action": "command", "mode": "console",
           "command": "say Redémarrage dans 5 min", "frequency": "daily", "hour": 3,
           "minute": 55}  # fmt: skip
    tid = client.post(f"{API}/apps/{app_id}/tasks", json=say).json()["id"]
    restart = {"name": "Redémarrage", "action": "restart", "frequency": "daily", "hour": 4}
    rid = client.post(f"{API}/apps/{app_id}/tasks", json=restart).json()["id"]
    listing = client.get(f"{API}/apps/{app_id}/tasks").json()
    assert listing["console"] is True and listing["services"] == ["server"]
    [first, second] = listing["tasks"]
    assert first["next_run_at"] and first["last_status"] is None and second["id"] == rid

    stopped = client.post(f"{API}/apps/{app_id}/tasks/{tid}/run").json()
    assert stopped["status"] == "failed" and "not running" in stopped["output"]

    gw.put(ContainerInfo(
        id="mc1", name="cube-server-1", image="mc", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "cube", "com.docker.compose.service": "server"},
    ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while rt.state.store.app("cube").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    gw.exec_results["rcon-cli say Redémarrage dans 5 min"] = (0, "")
    ran = client.post(f"{API}/apps/{app_id}/tasks/{tid}/run").json()
    assert ran["status"] == "ok" and gw.exec_calls[-1] == ["rcon-cli", "say", "Redémarrage",
                                                            "dans", "5", "min"]  # fmt: skip

    # The scheduler runs what is due, then plans the next run.
    with sqlite3.connect(rt.settings.db_path) as db:
        db.execute("UPDATE scheduled_task SET next_run_at = '2000-01-01 00:00:00.000000' "
                   "WHERE id = ?", (rid,))  # fmt: skip
    client.portal.call(rt.tasks_tick)
    row = next(
        t for t in client.get(f"{API}/apps/{app_id}/tasks").json()["tasks"] if t["id"] == rid
    )
    assert row["last_status"] == "queued" and row["last_output"].startswith("job #")
    assert row["next_run_at"] > "2001"
    wait_job(client, int(row["last_output"].split("#")[1]))

    shell = {**restart, "name": "Nettoyage", "action": "command", "command": "rm -f /tmp/x"}
    client.put(f"{API}/apps/{app_id}/tasks/{rid}", json={**shell, "enabled": False})
    row = next(
        t for t in client.get(f"{API}/apps/{app_id}/tasks").json()["tasks"] if t["id"] == rid
    )
    assert row["action"] == "command" and row["next_run_at"] is None  # disabled
    ran = client.post(f"{API}/apps/{app_id}/tasks/{rid}/run").json()
    assert ran["status"] == "ok" and gw.exec_calls[-1] == ["sh", "-c", "rm -f /tmp/x"]

    assert client.delete(f"{API}/apps/{app_id}/tasks/{rid}").status_code == 204
    gone = client.post(f"{API}/apps/{app_id}/tasks/{rid}/run")
    assert gone.status_code == 404 and code(gone) == "task_not_found"
