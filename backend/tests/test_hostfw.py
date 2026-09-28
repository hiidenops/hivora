from typing import Any

import pyotp
from helpers import API, admin, code

from hivora.hostfw.service import AGENT, HOST, parse_jail, parse_ufw_numbered

UFW_VERBOSE = """Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)
"""
UFW_NUMBERED = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     LIMIT IN    Anywhere
[ 2] 8443/tcp                   ALLOW IN    192.168.1.0/24
"""
F2B = "Status\n|- Number of jail:\t1\n`- Jail list:\tsshd\n"
SSHD = """Status for the jail: sshd
|- Filter
|  |- Currently failed:\t3
|  |- Total failed:\t40
`- Actions
   |- Currently banned:\t2
   |- Total banned:\t9
   `- Banned IP list:\t203.0.113.5 198.51.100.7
"""


def test_parsers() -> None:
    rules = parse_ufw_numbered(UFW_NUMBERED)
    assert [(r.number, r.to, r.action, r.source) for r in rules] == [
        (1, "22/tcp", "LIMIT IN", "Anywhere"), (2, "8443/tcp", "ALLOW IN", "192.168.1.0/24"),
    ]  # fmt: skip
    jail = parse_jail("sshd", SSHD)
    assert jail.banned == ["203.0.113.5", "198.51.100.7"] and jail.total_banned == 9
    assert jail.failed == 3


def host(*argv: str) -> str:
    return " ".join([*HOST, *argv])


def test_host_firewall_through_the_agent(client: Any) -> None:
    admin(client)
    gw = client.app.state.runtime.gateway
    off = client.get(f"{API}/host-firewall").json()
    assert off["agent"] is False
    assert code(client.post(f"{API}/host-firewall/ufw/rules",
                            json={"action": "allow", "port": 80})) == "host_agent_off"  # fmt: skip

    assert client.put(f"{API}/host-firewall/agent", json={"enabled": True}).status_code == 204
    assert gw.containers[AGENT].labels["io.hivora.self"] == "true"
    gw.exec_results[host("ufw", "status", "verbose")] = (0, UFW_VERBOSE)
    gw.exec_results[host("ufw", "status", "numbered")] = (0, UFW_NUMBERED)
    gw.exec_results[host("fail2ban-client", "status")] = (0, F2B)
    gw.exec_results[host("fail2ban-client", "status", "sshd")] = (0, SSHD)
    st = client.get(f"{API}/host-firewall", params={"fresh": True}).json()
    assert st["ufw_active"] and len(st["ufw_rules"]) == 2 and st["fail2ban_running"]
    assert st["jails"][0]["banned"] == ["203.0.113.5", "198.51.100.7"]
    firewall = next(n for n in client.get(f"{API}/topology").json()["nodes"]
                    if n["key"] == "firewall")  # fmt: skip
    assert firewall["ufw_active"] and firewall["banned"] == 2

    # Fixed command lines with validated arguments; nothing goes through a shell.
    rule = {"action": "allow", "port": 25565, "protocol": "tcp", "source": "192.168.1.0/24"}
    assert client.post(f"{API}/host-firewall/ufw/rules", json=rule).status_code == 200
    assert gw.exec_calls[-1] == [*HOST, "ufw", "allow", "proto", "tcp", "from",
                                 "192.168.1.0/24", "to", "any", "port", "25565"]  # fmt: skip
    bad = client.post(
        f"{API}/host-firewall/ufw/rules", json={**rule, "source": "1.2.3.4; rm -rf /"}
    )
    assert bad.status_code == 422
    assert client.delete(f"{API}/host-firewall/ufw/rules/2").status_code == 200
    assert gw.exec_calls[-1][-4:] == ["ufw", "--force", "delete", "2"]
    assert client.delete(f"{API}/host-firewall/ufw/rules/9").status_code == 422

    unban = client.post(f"{API}/host-firewall/fail2ban/sshd", json={"ip": "203.0.113.5"})
    assert unban.status_code == 200
    assert gw.exec_calls[-1][-5:] == ["fail2ban-client", "set", "sshd", "unbanip", "203.0.113.5"]
    assert (
        client.post(f"{API}/host-firewall/fail2ban/nope", json={"ip": "1.2.3.4"}).status_code == 422
    )

    # Turning UFW on keeps SSH reachable first (a 22/tcp rule already exists here).
    gw.exec_results[host("ufw", "status", "numbered")] = (0, "Status: inactive\n")
    client.put(f"{API}/host-firewall/ufw", json={"enabled": True})
    calls = [c[len(HOST) :] for c in gw.exec_calls[-4:]]
    assert ["ufw", "limit", "proto", "tcp", "from", "any", "to", "any", "port", "22"] in calls
    assert calls[-1] == ["ufw", "--force", "enable"]

    # With TOTP on, changes need a fresh confirmation.
    secret = client.post(f"{API}/auth/totp/enroll").json()["secret"]
    client.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
    locked = client.put(f"{API}/host-firewall/agent", json={"enabled": False})
    assert locked.status_code == 403 and code(locked) == "totp_required"


SS = """tcp   LISTEN 0 4096   0.0.0.0:22      0.0.0.0:*  users:(("sshd",pid=1,fd=3))
tcp   LISTEN 0 4096   0.0.0.0:8443    0.0.0.0:*  users:(("docker-proxy",pid=9,fd=4))
tcp   LISTEN 0 4096   127.0.0.1:5432  0.0.0.0:*  users:(("postgres",pid=7,fd=5))
tcp   LISTEN 0 4096   [::]:22         [::]:*     users:(("sshd",pid=1,fd=4))
udp   UNCONN 0 0      0.0.0.0:51820   0.0.0.0:*
tcp   LISTEN 0 511    0.0.0.0:80      0.0.0.0:*  users:(("nginx",pid=3,fd=6))
"""


def test_ss_and_jail_config() -> None:
    import pytest

    from hivora.core.errors import ValidationError
    from hivora.hostfw.service import jail_config, parse_ss

    rows = parse_ss(SS)
    assert [(r.protocol, r.address, r.port, r.process) for r in rows[:2]] == [
        ("tcp", "0.0.0.0", 22, "sshd"), ("tcp", "::", 22, "sshd"),
    ]  # fmt: skip
    assert any(r.port == 51820 and r.protocol == "udp" and r.process == "" for r in rows)
    text = jail_config({"sshd": {"enabled": True, "maxretry": 3, "bantime": "1h"}})
    assert "[sshd]\nenabled = true\nmaxretry = 3\nbantime = 1h" in text
    for bad in ({"ssh d": {}}, {"sshd": {"bantime": "1h; rm"}}, {"sshd": {"maxretry": 0}}):
        with pytest.raises(ValidationError):
            jail_config(bad)


def test_open_ports_routes_and_jail_settings(client: Any) -> None:
    from hivora.docker_gateway import ContainerInfo, ContainerState, PublishedPort
    from hivora.hostfw.service import JAIL_FILE

    admin(client)
    rt = client.app.state.runtime
    gw = rt.gateway
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})
    gw.exec_results[host("ufw", "status", "verbose")] = (0, UFW_VERBOSE)
    gw.exec_results[host("ufw", "status", "numbered")] = (0, UFW_NUMBERED)
    gw.exec_results[host("fail2ban-client", "status")] = (0, F2B)
    gw.exec_results[host("fail2ban-client", "status", "sshd")] = (0, SSHD)
    gw.exec_results[host("ss", "-H", "-tulpn")] = (0, SS)
    route = '[{"dst": "default", "gateway": "192.168.1.1", "dev": "eth0", "protocol": "dhcp"}]'
    gw.exec_results[host("ip", "-j", "route")] = (0, route)
    gw.exec_results[host("fail2ban-client", "get", "sshd", "maxretry")] = (0, "5\n")
    gw.put(ContainerInfo(id="h1", name="hivora", image="hivora", state=ContainerState.RUNNING,
                         labels={"io.hivora.app": "panel"},
                         ports=(PublishedPort(8443, "tcp", "0.0.0.0", 8443),)),
           "start")  # fmt: skip
    import time

    deadline = time.monotonic() + 3
    while not rt.state.store.containers():
        assert time.monotonic() < deadline
        time.sleep(0.02)

    ports = {
        (p["port"], p["address"]): p for p in client.get(f"{API}/host-firewall/listening").json()
    }
    assert ports[(22, "0.0.0.0")]["ufw"] == "allowed"  # rule 1: 22/tcp LIMIT
    assert (
        ports[(8443, "0.0.0.0")]["ufw"] == "bypassed" and ports[(8443, "0.0.0.0")]["app"] == "panel"
    )
    assert ports[(5432, "127.0.0.1")]["ufw"] == "local"
    assert ports[(80, "0.0.0.0")]["ufw"] == "blocked"  # no rule, UFW active

    r = client.get(f"{API}/host-firewall/routes").json()
    assert r["routes"][0]["gateway"] == "192.168.1.1"
    assert r["forwards"] == [{"port": 8443, "protocol": "tcp", "address": "0.0.0.0", "app": "panel",
                              "container_port": 8443}]  # fmt: skip

    assert client.get(f"{API}/host-firewall/fail2ban/settings").json()["sshd"]["maxretry"] == "5"
    saved = client.put(f"{API}/host-firewall/fail2ban/settings",
                       json={"jails": {"sshd": {"maxretry": 3, "bantime": "1h"}}})  # fmt: skip
    assert saved.status_code == 200
    write, reload = gw.exec_calls[-2][len(HOST) :], gw.exec_calls[-1][len(HOST) :]
    assert write[:2] == ["sh", "-c"] and write[2].endswith(JAIL_FILE) and "maxretry = 3" in write[4]
    assert "$1" in write[2] and "maxretry" not in write[2]  # the content is data, not shell code
    assert reload == ["fail2ban-client", "reload"]
