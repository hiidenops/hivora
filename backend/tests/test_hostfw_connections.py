# ruff: noqa: E501  (the samples below are real ss and conntrack output lines, kept whole)
import time
from typing import Any

from helpers import API, admin

from hivora.hostfw.connections import Flow, group, origin, parse_conntrack, parse_ss_established
from hivora.hostfw.service import HOST

# ss -H -tnp state established (no State column): two SSH sessions from the LAN, one
# client connection the host made itself (to 443: not inbound), a docker-proxy session.
ESTABLISHED = """0      0      192.168.1.10:22        192.168.1.12:53212   users:(("sshd",pid=812,fd=4))
0      36     192.168.1.10:22        192.168.1.12:53218   users:(("sshd",pid=900,fd=4))
0      0      192.168.1.10:41870     140.82.121.4:443     users:(("apt",pid=77,fd=6))
0      0      [::ffff:192.168.1.10]:25565 [::ffff:203.0.113.24]:51234 users:(("docker-proxy",pid=9,fd=7))
0      0      127.0.0.1:5432         127.0.0.1:40000      users:(("postgres",pid=7,fd=5))
"""
LISTENING = """tcp   LISTEN 0 4096   0.0.0.0:22      0.0.0.0:*  users:(("sshd",pid=1,fd=3))
tcp   LISTEN 0 4096   0.0.0.0:25565   0.0.0.0:*  users:(("docker-proxy",pid=9,fd=4))
tcp   LISTEN 0 4096   127.0.0.1:5432  0.0.0.0:*  users:(("postgres",pid=7,fd=5))
"""
# conntrack -L -p tcp --state ESTABLISHED: a player on the Minecraft app (by NAT), the same
# player's second connection, a container's own outbound connection, the summary line.
CONNTRACK = """tcp      6 431999 ESTABLISHED src=203.0.113.24 dst=192.168.1.10 sport=51234 dport=25565 src=172.18.0.2 dst=203.0.113.24 sport=25565 dport=51234 [ASSURED] mark=0 use=1
tcp      6 431998 ESTABLISHED src=203.0.113.24 dst=192.168.1.10 sport=51240 dport=25565 src=172.18.0.2 dst=203.0.113.24 sport=25565 dport=51240 [ASSURED] mark=0 use=1
tcp      6 300 ESTABLISHED src=172.18.0.2 dst=151.101.1.1 sport=40000 dport=25565 src=151.101.1.1 dst=192.168.1.10 sport=25565 dport=40000 [ASSURED] mark=0 use=1
conntrack v1.4.7 (conntrack-tools): 3 flow entries have been shown.
"""


def test_parsers_read_the_original_direction() -> None:
    host = parse_ss_established(ESTABLISHED)
    assert host[0] == (22, Flow("192.168.1.12", 22, "sshd"))
    assert host[3] == (25565, Flow("203.0.113.24", 25565, "docker-proxy"))  # IPv4 in IPv6 socket
    assert [f for f in parse_conntrack(CONNTRACK)] == [
        Flow("203.0.113.24", 25565), Flow("203.0.113.24", 25565), Flow("172.18.0.2", 25565)
    ]  # fmt: skip
    assert (origin("192.168.1.12"), origin("fe80::1"), origin("203.0.113.24")) == (
        "lan", "lan", "internet")  # fmt: skip


def test_group_counts_inbound_per_address_without_double_counting() -> None:
    seen: dict[str, float] = {"198.51.100.9": 1.0}  # gone since: forgotten
    rows = group(parse_ss_established(ESTABLISHED), parse_conntrack(CONNTRACK),
                 listening={22, 25565}, published={25565: "survie"},
                 containers={"172.18.0.2"}, seen=seen, now=50.0)  # fmt: skip
    assert rows == [
        # The Internet first: 2 by NAT (the docker-proxy one is the same, not a third).
        {"ip": "203.0.113.24", "origin": "internet", "connections": 2, "first_seen": 50.0,
         "targets": [{"port": 25565, "name": "survie"}]},
        {"ip": "192.168.1.12", "origin": "lan", "connections": 2, "first_seen": 50.0,
         "targets": [{"port": 22, "name": "sshd"}]},
    ]  # fmt: skip
    assert seen == {"203.0.113.24": 50.0, "192.168.1.12": 50.0}
    again = group([], parse_conntrack(CONNTRACK), listening=set(), published={25565: "survie"},
                  containers={"172.18.0.2"}, seen=seen, now=90.0)  # fmt: skip
    assert again[0]["first_seen"] == 50.0  # still connected: seen since the first time
    assert "192.168.1.12" not in seen


def host(*argv: str) -> str:
    return " ".join([*HOST, *argv])


def test_connections_route_through_the_agent(client: Any) -> None:
    from hivora.docker_gateway import ContainerInfo, ContainerState, PublishedPort

    admin(client)
    rt = client.app.state.runtime
    gw = rt.gateway
    assert client.get(f"{API}/host-firewall/connections").status_code == 409  # agent off
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})
    gw.exec_results[host("ss", "-H", "-tnp", "state", "established")] = (0, ESTABLISHED)
    gw.exec_results[host("ss", "-H", "-tulpn")] = (0, LISTENING)
    gw.put(ContainerInfo(id="mc", name="survie-server-1", image="mc", state=ContainerState.RUNNING,
                         labels={"io.hivora.app": "survie"}, ips=("172.18.0.2",),
                         ports=(PublishedPort(25565, "tcp", "0.0.0.0", 25565),)),
           "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while not rt.state.store.containers():
        assert time.monotonic() < deadline
        time.sleep(0.02)

    # No conntrack on the host: only the host's own sockets (docker-proxy shows one).
    gw.exec_results[host("conntrack", "-L", "-p", "tcp", "--state", "ESTABLISHED")] = (
        127, "nsenter: failed to execute conntrack: No such file or directory")  # fmt: skip
    r = client.get(f"{API}/host-firewall/connections").json()
    assert r["conntrack"] is False
    assert {(c["ip"], c["connections"]) for c in r["connections"]} == {
        ("203.0.113.24", 1), ("192.168.1.12", 2)}  # fmt: skip

    gw.exec_results[host("conntrack", "-L", "-p", "tcp", "--state", "ESTABLISHED")] = (0, CONNTRACK)
    r = client.get(f"{API}/host-firewall/connections").json()
    assert r["conntrack"] is True
    assert [(c["ip"], c["connections"], c["targets"]) for c in r["connections"]] == [
        ("203.0.113.24", 2, [{"port": 25565, "name": "survie"}]),
        ("192.168.1.12", 2, [{"port": 22, "name": "sshd"}]),
    ]  # fmt: skip


def test_conntrack_installed_by_a_job_on_request(client: Any) -> None:
    from helpers import wait_job

    from hivora.hostfw.connections import APT_UPDATE, INSTALL

    admin(client)
    gw = client.app.state.runtime.gateway
    url = f"{API}/host-firewall/connections/conntrack"
    assert client.post(url).status_code == 409  # agent off: nothing queued
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})

    # Debian or Ubuntu: the fixed install line, by a job; audited.
    r = client.post(url)
    assert r.status_code == 202 and r.json()["kind"] == "host_package"
    assert wait_job(client, r.json()["id"])["status"] == "succeeded"
    calls = [c[len(HOST) :] for c in gw.exec_calls]
    assert INSTALL in calls and APT_UPDATE not in calls
    deadline = time.monotonic() + 3  # the audit recorder writes in small batches
    while True:
        actions = [a["action"] for a in client.get(f"{API}/audit").json()]
        if {"hostfw.package_requested", "hostfw.package_installed"} <= set(actions):
            break
        assert time.monotonic() < deadline, actions
        time.sleep(0.1)

    # Stale package lists: refreshed once, then tried again (still failing here: reported).
    gw.exec_results[host(*INSTALL)] = (100, "E: Unable to locate package conntrack")
    job = wait_job(client, client.post(url).json()["id"])
    assert job["status"] == "failed" and APT_UPDATE in [c[len(HOST) :] for c in gw.exec_calls]

    # No apt-get on the host: refused with a clear error, nothing installed.
    gw.exec_results[host("env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "--version")] = (
        127, "nsenter: failed to execute env: apt-get: No such file or directory")  # fmt: skip
    job = wait_job(client, client.post(url).json()["id"])
    assert job["status"] == "failed" and "install conntrack by hand" in job["error"]
