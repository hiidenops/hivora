"""The host's packages (apt) and its reboot, through the host agent's fixed command lines."""

from typing import Any

from helpers import API, code, wait_job
from test_zone_actions import act, set_order, until, zone_with_apps

import hivora.system.host_updates as hu
from hivora.docker_gateway import ContainerState
from hivora.hostfw.service import HOST

# apt-get -s upgrade (LC_ALL=C): two upgrades, one from the security archive.
SIMULATION = """Reading package lists...
Calculating upgrade...
The following packages will be upgraded:
  openssl tzdata
Inst openssl [3.0.15-1~deb12u1] (3.0.17-1~deb12u2 Debian-Security:12/stable-security [arm64])
Inst tzdata [2024b-0+deb12u1] (2025b-0+deb12u1 Debian:12.12/stable [all])
Conf openssl (3.0.17-1~deb12u2 Debian-Security:12/stable-security [arm64])
"""
DONE = "SubState=exited\nResult=success\nExecMainStatus=0\n"


def host(*argv: str) -> str:
    return " ".join([*HOST, *argv])


def test_the_simulation_and_the_kernels_are_read() -> None:
    assert hu.parse_simulation(SIMULATION) == [
        {"name": "openssl", "current": "3.0.15-1~deb12u1", "candidate": "3.0.17-1~deb12u2",
         "security": True},
        {"name": "tzdata", "current": "2024b-0+deb12u1", "candidate": "2025b-0+deb12u1",
         "security": False},
    ]  # fmt: skip
    assert hu.newer_kernel("6.1.0-26-amd64", "6.1.0-25-amd64\n6.1.0-26-amd64\n6.1.0-28-amd64")
    assert not hu.newer_kernel("6.1.0-28-amd64", "6.1.0-26-amd64\n6.1.0-28-amd64")
    # Raspberry Pi OS: one kernel, several flavours: not a reboot
    assert not hu.newer_kernel("6.6.51+rpt-rpi-v8", "6.6.51+rpt-rpi-2712\n6.6.51+rpt-rpi-v8")


def test_checked_then_upgraded_by_a_job_through_the_agent(client: Any) -> None:
    from helpers import admin

    admin(client)
    gw = client.app.state.runtime.gateway
    assert client.get(f"{API}/system/host/updates").json()["agent"] is False
    assert code(client.post(f"{API}/system/host/updates/check")) == "host_agent_off"
    assert code(client.post(f"{API}/system/host/upgrade")) == "host_update_refused"
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})

    gw.exec_results[host(*hu.SIMULATE)] = (0, SIMULATION)
    gw.exec_results[host(*hu.REBOOT_FLAG)] = (1, "")
    gw.exec_results[host(*hu.RUNNING_KERNEL)] = (0, "6.1.0-26-amd64\n")
    gw.exec_results[host(*hu.KERNELS)] = (0, "6.1.0-26-amd64\n6.1.0-28-amd64\n")
    view = client.post(f"{API}/system/host/updates/check").json()
    assert [p["name"] for p in view["packages"]] == ["openssl", "tzdata"]
    assert view["reboot"] is True and view["checked_at"] and view["error"] is None
    calls = [c[len(HOST) :] for c in gw.exec_calls]
    assert calls[:2] == [hu.APT_UPDATE, hu.SIMULATE]

    # The upgrade runs in a transient unit of the host; followed until it ends.
    gw.exec_results[host(*hu.UNIT_SHOW)] = (0, DONE)
    r = client.post(f"{API}/system/host/upgrade")
    assert r.status_code == 202 and r.json()["kind"] == "host_upgrade"
    assert wait_job(client, r.json()["id"])["status"] == "succeeded"
    assert hu.UPGRADE in [c[len(HOST) :] for c in gw.exec_calls]

    failed = "SubState=failed\nResult=exit-code\nExecMainStatus=100\n"
    gw.exec_results[host(*hu.UNIT_SHOW)] = (0, failed)
    job = wait_job(client, client.post(f"{API}/system/host/upgrade").json()["id"])
    assert job["status"] == "failed" and "exit 100" in job["error"]


class Ctx:
    def __init__(self, job_id: int) -> None:
        self.job_id, self.lines = job_id, list[str]()

    async def log(self, line: str) -> None:
        self.lines.append(line)

    async def progress(self, *_: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


def test_reboot_stops_the_apps_in_order_then_starts_them_again(client: Any) -> None:
    rt, docker, ids = zone_with_apps(client)
    assert set_order(client, ids).status_code == 200
    assert wait_job(client, act(client, "start"))["status"] == "succeeded"
    docker.calls.clear()
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})
    gw = rt.gateway
    plan = client.get(f"{API}/system/host/reboot").json()
    assert sorted(a["name"] for a in plan["apps"]) == ["cloud", "lone", "pg", "redis"]

    gw.exec_results[host(*hu.DOCKER_AT_BOOT)] = (1, "disabled\n")
    job = wait_job(client, client.post(f"{API}/system/host/reboot").json()["id"])
    assert job["status"] == "failed" and "Docker does not start at boot" in job["error"]
    assert docker.calls == []  # nothing stopped

    # The host does not go down: the apps are started again, the job says why it failed.
    gw.exec_results[host(*hu.DOCKER_AT_BOOT)] = (0, "enabled\n")
    hu.REBOOT_WAIT_S = 0.2
    job = wait_job(client, client.post(f"{API}/system/host/reboot").json()["id"], within=20)
    assert job["status"] == "failed" and "did not reboot" in job["error"]
    assert hu.REBOOT in [c[len(HOST) :] for c in gw.exec_calls]
    stops, starts = docker.wave("stop"), docker.wave("start")
    assert stops.index("cloud") < min(stops.index("pg"), stops.index("redis"))  # needs them
    assert starts.index("cloud") > max(starts.index("pg"), starts.index("redis"))
    assert sorted(starts) == sorted(stops) == ["cloud", "lone", "pg", "redis"]

    # After a real reboot: the job resumes, sees another boot, starts the noted apps.
    for slug in ("pg", "lone"):
        docker.put(slug, ContainerState.EXITED)
    docker.calls.clear()
    hu.write_json(rt.settings.data_dir / hu.REBOOT_STATE,
                  {"job": 99, "boot_id": "before", "apps": [ids["pg"], ids["lone"]]})  # fmt: skip
    rt.host_updates.boot_id = lambda: "after"
    ctx = Ctx(99)
    client.portal.call(rt.host_updates._reboot, ctx)
    assert "the host rebooted" in ctx.lines and sorted(docker.wave("start")) == ["lone", "pg"]
    assert not (rt.settings.data_dir / hu.REBOOT_STATE).exists()
    until(lambda: rt.state.store.app("pg").status.value != "stopped")
