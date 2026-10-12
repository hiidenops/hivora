import asyncio
import functools
import json
import time
from typing import Any

import pyotp
from helpers import API, STRONG, admin, code, login, other_user, spy_events, wait_job
from sqlalchemy import text as sql

from hivora.hostfw.service import HOST

# ip -j route on the host: DHCP's default route and LAN, a Docker bridge, a route set by hand.
TABLE: list[dict[str, Any]] = [
    {"dst": "default", "gateway": "192.168.70.2", "dev": "enp2s0", "protocol": "dhcp"},
    {"dst": "172.18.0.0/16", "dev": "br-1", "protocol": "kernel", "scope": "link"},
    {"dst": "192.168.70.0/24", "dev": "enp2s0", "protocol": "dhcp", "scope": "link"},
    {"dst": "10.20.0.0/16", "gateway": "192.168.70.9", "dev": "enp2s0", "protocol": "static"},
]  # fmt: skip
ROUTES = f"{API}/host-firewall/static-routes"


class FakeIp:
    """``ip`` on the host as the agent runs it: the routes marked 241 change with replace
    and del; the rest of the table is fixed (``table``)."""

    def __init__(self, gw: Any) -> None:
        self.table = [dict(r) for r in TABLE]
        self.marked: dict[str, dict[str, Any]] = {}
        self.fail: dict[str, str] = {}  # destination -> ip's refusal of a replace
        self.slow_show: float = 0  # the next "show proto 241" waits this long first
        self.broken = False  # ip answers with an error instead of the table
        self.calls: list[list[str]] = []
        self.real = gw.exec_run
        gw.exec_run = self.exec_run

    async def exec_run(self, cid: str, cmd: list[str], user: str | None = None) -> Any:
        argv = cmd[len(HOST) :]
        if argv[:1] != ["ip"]:
            return await self.real(cid, cmd, user)
        self.calls.append(argv)
        if self.broken and argv[:2] == ["ip", "-j"]:
            return 1, 'Object "route" is unknown, try "ip help".'
        if argv == ["ip", "-j", "route", "show", "proto", "241"]:
            delay, self.slow_show = self.slow_show, 0
            await asyncio.sleep(delay)  # the answer is the state once the wait is over
            return 0, json.dumps(list(self.marked.values()))
        if argv == ["ip", "-j", "route"]:
            return 0, json.dumps(self.table + list(self.marked.values()))
        if argv[:3] == ["ip", "route", "replace"]:
            dst = argv[3]
            if dst in self.fail:
                return 2, self.fail[dst]
            shown = dst.removesuffix("/32")  # ip prints one address without its /32
            self.marked[dst] = {"dst": shown, "gateway": argv[5], "protocol": "241"}
            return 0, ""
        if argv[:3] == ["ip", "route", "del"]:
            return (0, "") if self.marked.pop(argv[3], None) else (2, "RTNETLINK: No such process")
        return 2, f"unexpected {argv}"


def agent_on(client: Any) -> tuple[Any, FakeIp]:
    admin(client)
    assert client.put(f"{API}/host-firewall/agent", json={"enabled": True}).status_code == 204
    rt = client.app.state.runtime
    return rt, FakeIp(rt.gateway)


def add(client: Any, destination: str, gateway: str = "192.168.70.20",
        **more: Any) -> dict[str, Any]:  # fmt: skip
    r = client.post(ROUTES, json={"destination": destination, "gateway": gateway, **more})
    assert r.status_code == 202, r.text
    return wait_job(client, r.json()["id"])


def test_routes_are_set_on_the_host_marked_241_and_only_those_are_removed(client: Any) -> None:
    _, ip = agent_on(client)
    ip.marked["10.7.0.0/16"] = {"dst": "10.7.0.0/16", "gateway": "192.168.70.21", "protocol": "241"}
    events, undo = spy_events(client)

    job = add(client, "10.8.0.9/24", dev="enp2s0", metric=50, note="VPN du bureau")
    assert job["status"] == "succeeded", job
    # The route set by hand (10.20.0.0/16) is never touched.
    assert ip.calls == [
        ["ip", "-j", "route"],  # the check, before anything is recorded
        ["ip", "-j", "route"],  # the job: the network now, then the marked routes
        ["ip", "-j", "route", "show", "proto", "241"],
        ["ip", "route", "del", "10.7.0.0/16", "proto", "241"],  # marked, no longer wanted
        ["ip", "route", "replace", "10.8.0.0/24", "via", "192.168.70.20", "dev", "enp2s0",
         "metric", "50", "proto", "241"],
    ]  # fmt: skip
    assert set(ip.marked) == {"10.8.0.0/24"}
    assert add(client, "10.9.0.7", "192.168.70.21")["status"] == "succeeded"  # one address
    listed = client.get(ROUTES).json()
    assert [(r["destination"], r["gateway"], r["dev"], r["metric"], r["note"], r["applied"])
            for r in listed] == [
        ("10.8.0.0/24", "192.168.70.20", "enp2s0", 50, "VPN du bureau", True),
        ("10.9.0.7/32", "192.168.70.21", None, None, None, True),  # shown by ip without /32
    ]  # fmt: skip
    assert listed[0]["created_by"] is not None
    ip.marked.pop("10.9.0.7/32")  # gone from the host (a reboot): not applied
    assert [r["applied"] for r in client.get(ROUTES).json()] == [True, False]

    ip.calls.clear()
    r = client.delete(f"{ROUTES}/{listed[0]['id']}")
    assert r.status_code == 202 and wait_job(client, r.json()["id"])["status"] == "succeeded"
    assert ["ip", "route", "del", "10.8.0.0/24", "proto", "241"] in ip.calls
    assert set(ip.marked) == {"10.9.0.7/32"}  # set again by the same job
    gone = client.delete(f"{ROUTES}/{listed[0]['id']}")
    assert gone.status_code == 404 and code(gone) == "route_not_found"
    undo()
    topics = [(t, p.get("target")) for t, p in events if t.startswith("hostfw.route")]
    assert topics == [("hostfw.route_added", "10.8.0.0/24"), ("hostfw.routes_applied", "proto 241"),
                      ("hostfw.route_added", "10.9.0.7/32"), ("hostfw.routes_applied", "proto 241"),
                      ("hostfw.route_removed", "10.8.0.0/24"),
                      ("hostfw.routes_applied", "proto 241")]  # fmt: skip


def test_routes_that_could_cut_the_host_off_write_and_run_nothing(client: Any) -> None:
    rt, ip = agent_on(client)
    refused = {
        ("0.0.0.0/0", "192.168.70.20"): (422, "invalid_route"),
        ("10.8.0.0/24;reboot", "192.168.70.20"): (422, "invalid_route"),
        ("10.8.0.0/24 via 1.2.3.4", "192.168.70.20"): (422, "request_invalid"),  # too long
        ("192.168.70.0/25", "192.168.70.20"): (409, "route_overlaps_connected"),
        ("172.18.4.0/24", "192.168.70.20"): (409, "route_overlaps_connected"),
        ("10.8.0.0/24", "10.99.0.1"): (409, "gateway_not_connected"),
    }
    for (destination, gateway), (status, error) in refused.items():
        r = client.post(ROUTES, json={"destination": destination, "gateway": gateway})
        assert (r.status_code, code(r)) == (status, error), destination
    unknown = client.post(ROUTES, json={"destination": "10.8.0.0/24", "gateway": "192.168.70.20",
                                        "dev": "wg0"})  # fmt: skip
    assert code(unknown) == "unknown_interface"
    own = functools.partial(rt.static_routes.add, "10.8.0.0/24", "192.168.70.20", dev=None,
                            metric=None, note=None, requester="10.8.0.33",
                            user_id=None)  # fmt: skip
    try:
        client.portal.call(own)
        raise AssertionError("a route over the requester accepted")
    except Exception as e:
        assert getattr(e, "code", None) == "route_contains_requester"
    assert add(client, "10.8.0.0/24")["status"] == "succeeded"
    again = client.post(ROUTES, json={"destination": "10.8.0.1/24", "gateway": "192.168.70.21"})
    assert again.status_code == 409 and code(again) == "route_exists"
    assert [r["destination"] for r in client.get(ROUTES).json()] == ["10.8.0.0/24"]
    jobs = [j for j in client.get(f"{API}/jobs").json() if j["kind"] == "host_route"]
    assert len(jobs) == 1  # only the accepted one
    replaced = {c[3] for c in ip.calls if c[:3] == ["ip", "route", "replace"]}
    assert replaced == {"10.8.0.0/24"}

    client.put(f"{API}/host-firewall/agent", json={"enabled": False})
    off = client.post(ROUTES, json={"destination": "10.9.0.0/24", "gateway": "192.168.70.20"})
    assert code(off) == "host_agent_off"
    route_id = client.get(ROUTES).json()[0]["id"]
    assert code(client.delete(f"{ROUTES}/{route_id}")) == "host_agent_off"
    assert client.get(ROUTES).json()[0]["applied"] is None  # the host cannot be asked

    # The host's table unreadable: nothing is added blindly.
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})
    ip.broken = True
    blind = client.post(ROUTES, json={"destination": "10.9.0.0/24", "gateway": "192.168.70.20"})
    assert blind.status_code == 409 and code(blind) == "host_command_failed"
    listed = [(r["destination"], r["applied"]) for r in client.get(ROUTES).json()]
    assert listed == [("10.8.0.0/24", None)]  # still listed, its state unknown


def test_each_route_is_checked_again_and_the_others_still_set(client: Any) -> None:
    _, ip = agent_on(client)
    assert add(client, "10.8.0.0/24")["status"] == "succeeded"
    assert add(client, "10.30.0.0/16")["status"] == "succeeded"
    ip.marked.clear()  # a reboot
    ip.table.append({"dst": "10.8.0.0/22", "dev": "enp3s0", "protocol": "kernel", "scope": "link"})
    ip.fail["10.30.0.0/16"] = "Error: Nexthop has invalid gateway."
    ip.table.append({"dst": "10.40.0.0/16", "dev": "enp2s0"})  # noise: no scope, ignored
    assert add(client, "10.50.0.0/16")["status"] == "failed"  # the job of this one
    job = next(j for j in client.get(f"{API}/jobs").json() if j["kind"] == "host_route")
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert "10.8.0.0/24: set aside (route_overlaps_connected)" in detail["log"]
    assert "Nexthop has invalid gateway" in detail["log"]
    assert set(ip.marked) == {"10.50.0.0/16"}  # the others set all the same
    kept = [r["destination"] for r in client.get(ROUTES).json()]
    assert kept == ["10.8.0.0/24", "10.30.0.0/16", "10.50.0.0/16"]  # the intention stays


def test_jobs_one_at_a_time_the_last_applies_the_table_as_it_is(client: Any) -> None:
    _, ip = agent_on(client)
    ip.slow_show = 0.4  # the first job reads the marked routes late
    first = client.post(ROUTES, json={"destination": "10.8.0.0/24", "gateway": "192.168.70.20"})
    deadline = time.monotonic() + 5
    while ["ip", "-j", "route", "show", "proto", "241"] not in ip.calls:  # it has read the table
        assert time.monotonic() < deadline
        time.sleep(0.01)
    second = client.post(ROUTES, json={"destination": "10.9.0.0/24", "gateway": "192.168.70.20"})
    for r in (first, second):
        assert wait_job(client, r.json()["id"])["status"] == "succeeded"
    # Without one job at a time, the first, late, would remove the route the second just set.
    assert set(ip.marked) == {"10.8.0.0/24", "10.9.0.0/24"}


def test_the_database_is_free_while_the_host_runs_ip(client: Any) -> None:
    rt, ip = agent_on(client)
    fake, writes = ip.exec_run, []

    async def exec_while_writing(cid: str, cmd: list[str], user: str | None = None) -> Any:
        async with rt.sessions() as s, s.begin():
            await s.execute(sql("UPDATE static_route SET note = note"))
        writes.append(cmd[len(HOST)])
        return await fake(cid, cmd, user)

    rt.gateway.exec_run = exec_while_writing
    assert add(client, "10.8.0.0/24")["status"] == "succeeded"
    rt.gateway.exec_run = fake
    assert len(writes) == 4  # the check, the two reads of the job, the replace


def test_hivora_starting_queues_the_routes_again(client: Any) -> None:
    rt, ip = agent_on(client)
    reapply = functools.partial(rt.static_routes.reapply)
    assert client.portal.call(reapply) is None  # no route: nothing runs on the host
    assert add(client, "10.8.0.0/24")["status"] == "succeeded"
    ip.marked.clear()  # a reboot
    job = client.portal.call(reapply)
    assert job is not None and wait_job(client, job.id)["status"] == "succeeded"
    assert set(ip.marked) == {"10.8.0.0/24"}
    client.put(f"{API}/host-firewall/agent", json={"enabled": False})
    assert client.portal.call(reapply) is None
    assert "static_routes" in rt.start.__code__.co_names  # Runtime.start calls it


def test_static_routes_are_for_admins_with_a_fresh_totp(client: Any) -> None:
    agent_on(client)
    client.post(f"{API}/users", json={"username": "olive", "role": "operator",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as operator:
        login(operator, "olive", "temporary-pass-1")
        operator.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert operator.get(ROUTES).status_code == 403
        body = {"destination": "10.8.0.0/24", "gateway": "192.168.70.20"}
        assert operator.post(ROUTES, json=body).status_code == 403
        assert operator.delete(f"{ROUTES}/1").status_code == 403
    secret = client.post(f"{API}/auth/totp/enroll").json()["secret"]
    client.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
    locked = client.post(ROUTES, json={"destination": "10.8.0.0/24", "gateway": "192.168.70.20"})
    assert locked.status_code == 403 and code(locked) == "totp_required"
    assert client.get(ROUTES).json() == []
