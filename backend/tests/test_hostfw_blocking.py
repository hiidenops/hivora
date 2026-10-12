import asyncio
import functools
import time
from typing import Any

import pyotp
from helpers import API, STRONG, admin, code, login, other_user, spy_events, wait_job
from sqlalchemy import text as sql

from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.hostfw.blocking import RESTORE
from hivora.hostfw.blocklist import restore_text
from hivora.hostfw.service import HOST

V4 = "203.0.113.24"
V6 = "2001:db8::7"


def host(*argv: str) -> str:
    return " ".join([*HOST, *argv])


def restore(family: int, *addresses: str) -> list[str]:
    tool = "iptables-restore" if family == 4 else "ip6tables-restore"
    return ["sh", "-c", RESTORE.format(tool), "hivora",
            restore_text(list(addresses), 4 if family == 4 else 6)]  # fmt: skip


def agent_on(client: Any) -> Any:
    admin(client)
    assert client.put(f"{API}/host-firewall/agent", json={"enabled": True}).status_code == 204
    return client.app.state.runtime


def calls_since(gw: Any, start: int) -> list[list[str]]:
    return [c[len(HOST) :] for c in gw.exec_calls[start:]]


def block(client: Any, address: str, note: str | None = None) -> dict[str, Any]:
    r = client.post(f"{API}/host-firewall/blocked", json={"address": address, "note": note})
    assert r.status_code == 202, r.text
    return wait_job(client, r.json()["id"])


def test_a_block_rebuilds_the_chain_then_makes_input_and_docker_jump_to_it(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    absent = (1, "iptables: Bad rule (does a matching rule exist in that chain?).")
    for tool, chain in (("iptables", "INPUT"), ("iptables", "DOCKER-USER"),
                        ("ip6tables", "INPUT"), ("ip6tables", "DOCKER-USER")):  # fmt: skip
        gw.exec_results[host(tool, "-C", chain, "-j", "HIVORA-BLOCK")] = absent
    no_chain = (1, "ip6tables: No chain/target/match by that name.")
    gw.exec_results[host("ip6tables", "-I", "DOCKER-USER", "1", "-j", "HIVORA-BLOCK")] = no_chain
    events, undo = spy_events(client)
    start = len(gw.exec_calls)

    job = block(client, f"::ffff:{V4}", note="vu sur survie :25565")  # canonical: IPv4
    undo()
    assert job["status"] == "succeeded", job
    assert calls_since(gw, start) == [
        restore(4, V4),
        ["iptables", "-C", "INPUT", "-j", "HIVORA-BLOCK"],
        ["iptables", "-I", "INPUT", "1", "-j", "HIVORA-BLOCK"],
        ["iptables", "-C", "DOCKER-USER", "-j", "HIVORA-BLOCK"],
        ["iptables", "-I", "DOCKER-USER", "1", "-j", "HIVORA-BLOCK"],
        restore(6),  # nothing in IPv6: the chain emptied
        ["ip6tables", "-C", "INPUT", "-j", "HIVORA-BLOCK"],
        ["ip6tables", "-I", "INPUT", "1", "-j", "HIVORA-BLOCK"],
        ["ip6tables", "-C", "DOCKER-USER", "-j", "HIVORA-BLOCK"],
        ["ip6tables", "-I", "DOCKER-USER", "1", "-j", "HIVORA-BLOCK"],
    ]
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "HIVORA-BLOCK (IPv4): 1 address(es)" in log
    assert "no DOCKER-USER chain" in log  # IPv6 here: the host's services only
    listed = client.get(f"{API}/host-firewall/blocked").json()
    assert [(b["address"], b["note"]) for b in listed] == [(V4, "vu sur survie :25565")]
    assert listed[0]["created_by"] is not None
    topics = [(t, p.get("target")) for t, p in events if t.startswith("hostfw.")]
    assert topics == [("hostfw.blocked", V4), ("hostfw.blocklist_applied", "HIVORA-BLOCK")]

    # The jumps there now (the fake answers 0 by default): none inserted again.
    for tool, chain in (("iptables", "INPUT"), ("iptables", "DOCKER-USER"),
                        ("ip6tables", "INPUT"), ("ip6tables", "DOCKER-USER")):  # fmt: skip
        del gw.exec_results[host(tool, "-C", chain, "-j", "HIVORA-BLOCK")]
    start = len(gw.exec_calls)
    assert block(client, V6)["status"] == "succeeded"
    calls = calls_since(gw, start)
    assert calls[0] == restore(4, V4) and restore(6, V6) in calls
    assert not any("-I" in c for c in calls)

    assert code(client.post(f"{API}/host-firewall/blocked", json={"address": V4})) == (
        "address_already_blocked")  # fmt: skip
    start = len(gw.exec_calls)
    r = client.delete(f"{API}/host-firewall/blocked/{V4}")
    assert r.status_code == 202 and wait_job(client, r.json()["id"])["status"] == "succeeded"
    assert calls_since(gw, start)[0] == restore(4)  # the last IPv4 one: the chain emptied
    assert [b["address"] for b in client.get(f"{API}/host-firewall/blocked").json()] == [V6]
    gone = client.delete(f"{API}/host-firewall/blocked/{V4}")
    assert gone.status_code == 404 and code(gone) == "address_not_blocked"


def test_refused_addresses_write_and_run_nothing(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    gw.put(ContainerInfo(id="mc", name="survie-server-1", image="mc", state=ContainerState.RUNNING,
                         labels={"io.hivora.app": "survie"}, ips=("172.18.0.2",)),
           "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while not rt.state.store.containers():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    start = len(gw.exec_calls)
    refused = {
        "1.2.3.4 -j ACCEPT": (422, "invalid_address"),
        "203.0.113.0/24": (422, "invalid_address"),
        "127.0.0.1": (422, "invalid_address"),
        "192.168.1.10": (409, "host_address"),  # the host's LAN address
        "203.0.113.7": (409, "host_address"),  # its public address
        "::ffff:172.18.0.2": (409, "host_address"),  # a container's
    }
    for address, (status, error) in refused.items():
        r = client.post(f"{API}/host-firewall/blocked", json={"address": address})
        assert (r.status_code, code(r)) == (status, error), address
    # The requester's own address (the test client has none: asked of the service directly).
    own = functools.partial(rt.blocking.block, "198.51.100.20", None,
                            requester="::ffff:198.51.100.20", user_id=None)  # fmt: skip
    try:
        client.portal.call(own)
        raise AssertionError("own address accepted")
    except Exception as e:
        assert getattr(e, "code", None) == "own_address"
    assert client.get(f"{API}/host-firewall/blocked").json() == []
    jobs = client.get(f"{API}/jobs").json()
    assert not [j for j in jobs if j["kind"] == "host_firewall"]
    assert gw.exec_calls[start:] == []

    # The agent off: neither a block nor an unblock is recorded.
    client.put(f"{API}/host-firewall/agent", json={"enabled": False})
    assert code(client.post(f"{API}/host-firewall/blocked", json={"address": V4})) == (
        "host_agent_off")  # fmt: skip
    assert code(client.delete(f"{API}/host-firewall/blocked/{V4}")) == "host_agent_off"
    assert client.get(f"{API}/host-firewall/blocked").json() == []


def test_a_failed_restore_keeps_the_intention(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    gw.exec_results[host(*restore(4, V4))] = (2, "iptables-restore: line 3 failed")
    job = block(client, V4)
    assert job["status"] == "failed" and "iptables-restore failed" in job["error"]
    assert [b["address"] for b in client.get(f"{API}/host-firewall/blocked").json()] == [V4]


def test_ip6tables_missing_only_matters_with_an_ipv6_address(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    missing = (127, "sh: ip6tables-restore: not found")
    gw.exec_results[host(*restore(6))] = missing
    job = block(client, V4)
    assert job["status"] == "succeeded"
    log = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    assert "ip6tables-restore: not on the host" in log
    gw.exec_results[host(*restore(6, V6))] = missing
    assert block(client, V6)["status"] == "failed"


def test_jobs_one_at_a_time_the_last_applies_the_table_as_it_is(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    real_exec = gw.exec_run
    applied: list[str] = []
    entered: list[str] = []

    async def slow_restore(cid: str, cmd: list[str], user: str | None = None) -> Any:
        if "iptables-restore --noflush" in " ".join(cmd):
            entered.append(cmd[-1])
            if len(entered) == 1:
                await asyncio.sleep(0.4)  # the first job slow: without the lock, the second
            applied.append(cmd[-1])  # would read the table and apply it before the first ends
        return await real_exec(cid, cmd, user)

    gw.exec_run = slow_restore
    first = client.post(f"{API}/host-firewall/blocked", json={"address": V4}).json()["id"]
    deadline = time.monotonic() + 5
    while not entered:  # the first job has read the table, and is applying it slowly
        assert time.monotonic() < deadline
        time.sleep(0.01)
    second = client.post(f"{API}/host-firewall/blocked", json={"address": "198.51.100.3"})
    for job_id in (first, second.json()["id"]):
        assert wait_job(client, job_id)["status"] == "succeeded"
    gw.exec_run = real_exec
    assert applied[-1] == restore_text([V4, "198.51.100.3"], 4)


def test_the_database_is_free_while_the_host_runs_the_rules(client: Any) -> None:
    rt = agent_on(client)
    gw = rt.gateway
    real_exec, writes = gw.exec_run, []

    async def exec_while_writing(cid: str, cmd: list[str], user: str | None = None) -> Any:
        async with rt.sessions() as s, s.begin():
            await s.execute(sql("UPDATE blocked_address SET note = note"))
        writes.append(cmd[-1][:20])
        return await real_exec(cid, cmd, user)

    gw.exec_run = exec_while_writing
    assert block(client, V4)["status"] == "succeeded"
    gw.exec_run = real_exec
    assert len(writes) == 6  # two restores, four checks: each with the database free


def test_hivora_starting_queues_the_rules_again(client: Any) -> None:
    rt = agent_on(client)
    reapply = functools.partial(rt.blocking.reapply)
    assert client.portal.call(reapply) is None  # nothing blocked: the chain is never created
    assert block(client, V4)["status"] == "succeeded"
    job = client.portal.call(reapply)
    assert job is not None and wait_job(client, job.id)["status"] == "succeeded"
    client.put(f"{API}/host-firewall/agent", json={"enabled": False})
    assert client.portal.call(reapply) is None  # the agent off: nothing runs on the host
    started = rt.start.__code__.co_names
    assert "reapply" in started  # Runtime.start calls it


def test_blocking_is_for_admins_with_a_fresh_totp(client: Any) -> None:
    agent_on(client)
    client.post(f"{API}/users", json={"username": "olive", "role": "operator",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as operator:
        login(operator, "olive", "temporary-pass-1")
        operator.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert operator.get(f"{API}/host-firewall/blocked").status_code == 403
        assert operator.post(f"{API}/host-firewall/blocked",
                             json={"address": V4}).status_code == 403  # fmt: skip
        assert operator.delete(f"{API}/host-firewall/blocked/{V4}").status_code == 403
    secret = client.post(f"{API}/auth/totp/enroll").json()["secret"]
    client.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
    locked = client.post(f"{API}/host-firewall/blocked", json={"address": V4})
    assert locked.status_code == 403 and code(locked) == "totp_required"
    assert client.get(f"{API}/host-firewall/blocked").json() == []
