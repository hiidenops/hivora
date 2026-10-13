import time
from typing import Any

from helpers import API, STRONG, admin, code, login, other_user, spy_events, wait_job

from hivora.docker_gateway import ContainerInfo, ContainerState, Health

ZONES = f"{API}/zones"


class Docker:
    """The apps' containers as Docker would show them: an app started runs (healthy, or
    still starting as told by ``health``), an app stopped has exited. Records the order."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.health: dict[str, Health] = {}
        self.calls: list[tuple[str, str]] = []
        lifecycle = rt.apps.lifecycle
        start, stop = lifecycle.start, lifecycle.stop

        async def started(app_id: int) -> Any:
            job = await start(app_id)
            self.calls.append(("start", job.app_slug))
            self.put(job.app_slug, ContainerState.RUNNING)
            return job

        async def stopped(app_id: int) -> Any:
            job = await stop(app_id)
            self.calls.append(("stop", job.app_slug))
            self.put(job.app_slug, ContainerState.EXITED)
            return job

        lifecycle.start, lifecycle.stop = started, stopped

    def put(self, slug: str, state: ContainerState) -> None:
        running = state is ContainerState.RUNNING
        health = self.health.get(slug, Health.NONE) if running else Health.NONE
        self.rt.gateway.put(ContainerInfo(
            id=f"ctr-{slug}", name=f"{slug}-server-1", image="nginx", state=state, health=health,
            exit_code=0 if state is ContainerState.EXITED else None,
            labels={"io.hivora.app": slug, "com.docker.compose.service": "server"},
        ), "start" if state is ContainerState.RUNNING else "die")  # fmt: skip

    def wave(self, how: str) -> list[str]:
        return [slug for action, slug in self.calls if action == how]


def zone_with_apps(client: Any) -> tuple[Any, Docker, dict[str, int]]:
    """Zone "Labo": pg, redis, cloud (after pg and redis), lone; and "Autre" with one app."""
    admin(client)
    rt = client.app.state.runtime
    for name in ("Labo", "Autre"):
        assert client.post(ZONES, json={"name": name, "color": "#888888"}).status_code == 201
    ids: dict[str, int] = {}
    apps = (("pg", "labo"), ("redis", "labo"), ("cloud", "labo"), ("lone", "labo"),
            ("ailleurs", "autre"))  # fmt: skip
    for port, (name, zone) in enumerate(apps, start=8401):
        r = client.post(f"{API}/apps", json={"template": "nginx", "name": name, "zone": zone,
                                             "inputs": {"web_port": port}})  # fmt: skip
        assert r.status_code == 202, r.text
        assert wait_job(client, r.json()["job"]["id"])["status"] == "succeeded"
        ids[name] = r.json()["app"]["id"]
    return rt, Docker(rt), ids


def set_order(client: Any, ids: dict[str, int], timeout_s: int = 120) -> Any:
    deps = [{"app": ids["cloud"], "after": ids["pg"]}, {"app": ids["cloud"], "after": ids["redis"]}]
    return client.put(f"{ZONES}/labo/startup", json={"dependencies": deps, "timeout_s": timeout_s})


def act(client: Any, action: str) -> int:
    r = client.post(f"{ZONES}/labo/actions", json={"action": action})
    assert r.status_code == 202, r.text
    job_id: int = r.json()["id"]
    return job_id


def until(condition: Any, within: float = 10) -> None:
    deadline = time.monotonic() + within
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_the_start_order_is_read_set_and_checked(client: Any) -> None:
    _, _, ids = zone_with_apps(client)
    view = client.get(f"{ZONES}/labo/startup").json()
    assert [a["name"] for a in view["apps"]] == ["cloud", "lone", "pg", "redis"]  # by name
    assert (view["dependencies"], view["timeout_s"]) == ([], 120)
    assert view["steps"] == [sorted(ids[n] for n in ("pg", "redis", "cloud", "lone"))]

    r = set_order(client, ids, timeout_s=300)
    assert r.status_code == 200, r.text
    assert r.json()["steps"] == [sorted([ids["pg"], ids["redis"], ids["lone"]]), [ids["cloud"]]]
    assert r.json()["timeout_s"] == 300

    def put(deps: list[dict[str, int]], timeout_s: int = 120) -> Any:
        return client.put(f"{ZONES}/labo/startup",
                          json={"dependencies": deps, "timeout_s": timeout_s})  # fmt: skip

    refused = [
        ([{"app": ids["pg"], "after": ids["pg"]}], 422, "invalid_dependency"),
        ([{"app": ids["pg"], "after": ids["ailleurs"]}], 409, "dependency_outside_zone"),
        ([{"app": ids["pg"], "after": ids["cloud"]}, {"app": ids["cloud"], "after": ids["pg"]}],
         409, "dependency_cycle"),
    ]  # fmt: skip
    for deps, status, error in refused:
        r = put(deps)
        assert (r.status_code, code(r)) == (status, error), deps
    assert put([], 5).status_code == 422  # the timeout's bounds
    loop = [{"app": ids["pg"], "after": ids["cloud"]}, {"app": ids["cloud"], "after": ids["pg"]}]
    cycle = put(loop)
    assert sorted(cycle.json()["error"]["details"]["apps"]) == sorted([ids["pg"], ids["cloud"]])
    view = client.get(f"{ZONES}/labo/startup").json()  # nothing changed by the refusals
    assert (len(view["dependencies"]), view["timeout_s"]) == (2, 300)
    assert client.get(f"{ZONES}/nulle-part/startup").status_code == 404


def test_the_zone_starts_wave_by_wave_each_waiting_for_health(client: Any) -> None:
    _, docker, ids = zone_with_apps(client)
    assert set_order(client, ids).status_code == 200
    docker.health["pg"] = Health.STARTING  # PostgreSQL takes its time
    events, undo = spy_events(client)
    job_id = act(client, "start")
    until(lambda: "pg" in docker.wave("start"))
    time.sleep(1.5)  # pg still starting: cloud waits for it
    assert sorted(docker.wave("start")) == ["lone", "pg", "redis"]
    docker.health["pg"] = Health.HEALTHY
    docker.put("pg", ContainerState.RUNNING)  # now healthy
    job = wait_job(client, job_id, within=20)
    undo()
    assert job["status"] == "succeeded", job
    assert docker.wave("start")[-1] == "cloud"  # second wave, once pg and redis are healthy
    log = client.get(f"{API}/jobs/{job_id}").json()["log"]
    assert "start, wave 1: pg, redis, lone" in log and "start, wave 2: cloud" in log
    topics = [(t, p.get("action")) for t, p in events if t.startswith("zone.")]
    assert topics == [("zone.action_requested", "start"), ("zone.action_done", "start")]


def test_stop_goes_backwards_and_restart_stops_then_starts(client: Any) -> None:
    _, docker, ids = zone_with_apps(client)
    assert set_order(client, ids).status_code == 200
    assert wait_job(client, act(client, "stop"), within=20)["status"] == "succeeded"
    stopped = docker.wave("stop")
    assert stopped[0] in ("cloud", "lone") and stopped.index("cloud") < stopped.index("pg")
    assert stopped.index("cloud") < stopped.index("redis")  # cloud first: it needs them
    docker.calls.clear()
    assert wait_job(client, act(client, "restart"), within=20)["status"] == "succeeded"
    actions = [a for a, _ in docker.calls]
    assert actions == ["stop"] * 4 + ["start"] * 4  # all stopped, then all started
    assert docker.wave("start")[-1] == "cloud"


def test_an_app_that_never_gets_healthy_holds_back_only_its_dependents(client: Any) -> None:
    _, docker, ids = zone_with_apps(client)
    assert set_order(client, ids, timeout_s=10).status_code == 200
    docker.health["pg"] = Health.STARTING  # never healthy
    job_id = act(client, "start")
    # One zone action at a time: a second one is refused while the first runs.
    until(lambda: "pg" in docker.wave("start"))
    busy = client.post(f"{ZONES}/labo/actions", json={"action": "stop"})
    assert busy.status_code == 409 and code(busy) == "zone_action_running"
    job = wait_job(client, job_id, within=30)
    assert job["status"] == "failed"
    assert "pg: still starting after 10 s" in job["error"]
    assert "cloud: not started, waits for pg" in job["error"]
    assert sorted(docker.wave("start")) == ["lone", "pg", "redis"]  # the other branches went on


def test_an_app_moved_to_another_zone_loses_its_dependencies(client: Any) -> None:
    _, _, ids = zone_with_apps(client)
    assert set_order(client, ids).status_code == 200
    for zone in ("autre", "labo"):  # away, then back: the old dependency does not come back
        r = client.put(f"{API}/apps/{ids['pg']}/zone", json={"zone": zone})
        assert r.status_code == 202, r.text
        assert wait_job(client, r.json()["id"])["status"] == "succeeded"
    view = client.get(f"{ZONES}/labo/startup").json()
    assert view["dependencies"] == [{"app": ids["cloud"], "after": ids["redis"]}]
    assert ids["pg"] in [a["id"] for a in view["apps"]]


def test_an_app_whose_job_fails_holds_back_its_dependents(client: Any) -> None:
    rt, docker, ids = zone_with_apps(client)
    assert set_order(client, ids).status_code == 200
    from hivora.jobs import JobKind

    handlers = rt.jobs._handlers
    real = handlers[JobKind.START]

    async def start(ctx: Any) -> None:
        if ctx.app_slug == "redis":
            raise RuntimeError("compose up failed")
        await real(ctx)

    handlers[JobKind.START] = start
    job = wait_job(client, act(client, "start"), within=20)
    handlers[JobKind.START] = real
    assert job["status"] == "failed"
    assert "redis: its job failed" in job["error"]
    assert "cloud: not started, waits for redis" in job["error"]
    assert "cloud" not in docker.wave("start")


def test_an_app_never_deployed_is_left_out(client: Any) -> None:
    rt, docker, ids = zone_with_apps(client)
    import sqlite3

    with sqlite3.connect(rt.settings.db_path) as conn:  # as an app whose deploy never ran
        conn.execute("UPDATE application SET current_revision_id = NULL WHERE id = ?",
                     (ids["lone"],))  # fmt: skip
    view = client.get(f"{ZONES}/labo/startup").json()
    assert ids["lone"] not in [a["id"] for a in view["apps"]]
    assert wait_job(client, act(client, "start"), within=20)["status"] == "succeeded"
    assert "lone" not in docker.wave("start")


def test_viewers_read_the_order_operators_change_it(client: Any) -> None:
    _, _, ids = zone_with_apps(client)
    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    events, undo = spy_events(client)
    assert set_order(client, ids).status_code == 200
    undo()
    assert [t for t, _ in events if t.startswith("zone.")] == ["zone.start_order_changed"]
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{ZONES}/labo/startup").status_code == 200
        assert viewer.put(f"{ZONES}/labo/startup", json={"dependencies": []}).status_code == 403
        assert viewer.post(f"{ZONES}/labo/actions", json={"action": "start"}).status_code == 403
