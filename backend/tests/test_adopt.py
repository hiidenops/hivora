import time
from typing import Any

from helpers import API, admin, code, wait_job

from hivora.docker_gateway import ContainerInfo, ContainerState, PublishedPort


def stack(project: str, service: str, cid: str, **labels: str) -> ContainerInfo:
    return ContainerInfo(
        id=cid, name=f"{project}-{service}-1", image=f"{service}:latest",
        state=ContainerState.RUNNING,
        labels={"com.docker.compose.project": project, "com.docker.compose.service": service,
                "com.docker.compose.project.working_dir": f"/home/me/{project}", **labels},
        ports=(PublishedPort(80, "tcp", "0.0.0.0", 8097),) if service == "web" else (),
    )  # fmt: skip


def test_adopt_a_running_stack_then_forget_it(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    gw = rt.gateway
    gw.put(stack("mystack", "web", "w1"), "start")
    gw.put(stack("mystack", "cache", "c1"), "start")
    gw.put(stack("hivora", "hivora", "h1", **{"io.hivora.self": "true"}), "start")
    deadline = time.monotonic() + 3
    while len(rt.state.store.containers()) < 3:
        assert time.monotonic() < deadline
        time.sleep(0.02)

    [found] = client.get(f"{API}/apps/discover").json()  # Hivora itself is not offered
    assert found == {"project": "mystack", "services": ["cache", "web"], "running": 2,
                     "containers": 2, "working_dir": "/home/me/mystack"}  # fmt: skip

    client.post(f"{API}/zones", json={"name": "Jeux", "color": "#d97706"})
    body = {"project": "mystack", "name": "Ma stack", "zone": "jeux"}
    adopted = client.post(f"{API}/apps/adopt", json=body)
    assert adopted.status_code == 201
    app_id = adopted.json()["id"]
    detail = client.get(f"{API}/apps/{app_id}").json()
    assert detail["name"] == "Ma stack" and detail["template"] is None
    assert detail["status"] == "healthy" and detail["origin"] == "adopted"
    assert detail["zone_id"] is not None
    assert any(p["host_port"] == 8097 for p in detail["ports"])
    assert client.get(f"{API}/apps/discover").json() == []
    again = client.post(f"{API}/apps/adopt", json={"project": "mystack"})
    assert again.status_code == 404

    for action in ("stop", "start", "restart"):
        job = client.post(f"{API}/apps/{app_id}/{action}").json()
        assert wait_job(client, job["id"])["status"] == "succeeded", action
    assert client.get(f"{API}/apps/{app_id}/settings").status_code == 409  # no template

    plan = client.get(f"{API}/apps/{app_id}/removal-plan").json()
    assert plan["containers"] == [] and plan["data"] == []  # nothing is removed
    job = client.delete(f"{API}/apps/{app_id}").json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert gw.containers["w1"].state is ContainerState.RUNNING  # still there, untouched
    assert [c["project"] for c in client.get(f"{API}/apps/discover").json()] == ["mystack"]
    assert code(client.get(f"{API}/apps/{app_id}")) == "app_not_found"
