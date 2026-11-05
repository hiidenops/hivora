import ipaddress
import time
from pathlib import Path
from typing import Any

from hivora.docker_gateway import ContainerInfo, ContainerState, NetworkInfo
from hivora.vpn import wireguard as wg


def test_keys_configs_and_dump() -> None:
    private, public = wg.keypair()
    assert len(private) == len(public) == 44 and wg.public_of(private) == public

    peers = [wg.Peer("phone", "10.8.0.2", "PUB2")]
    conf = wg.server_conf("PRIV", "10.8.0.0/24", "10.8.0.1", 51820, "wg0", peers, "/config/acl.sh")
    assert "; sh /config/acl.sh" in conf
    assert "Address = 10.8.0.1/24" in conf and "ListenPort = 51820" in conf
    assert "-s 10.8.0.0/24 -j MASQUERADE" in conf  # every interface: LAN and zone networks
    assert "# phone\n[Peer]\nPublicKey = PUB2\nAllowedIPs = 10.8.0.2/32" in conf

    assert wg.free_address("10.8.0.0/24", {"10.8.0.1", "10.8.0.2"}) == "10.8.0.3"
    assert wg.network("10.9.0.0/24", "10.9.0.254") == (ipaddress.ip_network("10.9.0.0/24"),
                                                       "10.9.0.254")  # fmt: skip
    for bad in (("10.9.0.0/31", ""), ("10.9.0.0/24", "10.8.0.1"), ("10.9.0.1/24", "")):
        try:
            wg.network(*bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert wg.free_address("10.8.0.0/30", {"10.8.0.1", "10.8.0.2"}) is None

    dump = "PRIV\tPUB\t51820\toff\nPUB2\t(none)\t1.2.3.4:5\t10.8.0.2/32\t1700000000\t10\t20\t25\n"
    stats = wg.parse_dump(dump, 1_700_000_060)["PUB2"]
    assert (stats.rx, stats.tx) == (10, 20)
    assert (stats.latest_handshake or "").startswith("2023-11-14")
    assert stats.online and stats.endpoint == "1.2.3.4:5"
    assert not wg.parse_dump(dump, 1_700_000_500)["PUB2"].online
    assert (
        wg.parse_dump("PRIV\tPUB\t51820\toff\nP3\t(none)\t(none)\t10.8.0.3/32\t0\t0\t0\toff\n", 0)[
            "P3"
        ].latest_handshake
        is None
    )


def test_access_rights_script_and_routes() -> None:
    zone = "172.20.0.0/16"
    only_zone = wg.Access("10.8.0.2", internet=False, lan=False, zones=(zone,))
    everything = wg.Access("10.8.0.3", internet=True, lan=True, zones=())
    script = wg.acl_script("wg0", [only_zone, everything], [zone, "172.21.0.0/16"])
    lines = script.splitlines()
    first = lines.index("iptables -A HIVORA-VPN-NEW -s 10.8.0.2/32 -d 172.20.0.0/16 -j ACCEPT")
    assert lines[first + 1] == "iptables -A HIVORA-VPN-NEW -s 10.8.0.2/32 -d 172.21.0.0/16 -j DROP"
    assert "iptables -A HIVORA-VPN-NEW -s 10.8.0.2/32 -d 192.168.0.0/16 -j DROP" in lines
    assert "iptables -A HIVORA-VPN-NEW -s 10.8.0.2/32 -j DROP" in lines  # no Internet
    # Denied zones come before the local network, which would otherwise open them.
    rule = "iptables -A HIVORA-VPN-NEW -s 10.8.0.3/32 -d "
    drop, lan = f"{rule}172.20.0.0/16 -j DROP", f"{rule}172.16.0.0/12 -j ACCEPT"
    assert lines.index(drop) < lines.index(lan)
    assert "iptables -A HIVORA-VPN-NEW -s 10.8.0.3/32 -j ACCEPT" in lines
    assert lines[-1] == "iptables -E HIVORA-VPN-NEW HIVORA-VPN" and "set -e" in lines
    assert wg.routes("10.8.0.0/24", only_zone) == ["10.8.0.0/24", zone]
    assert wg.routes("10.8.0.0/24", everything) == ["0.0.0.0/0"]


def test_vpn_clients_and_linked_zones(client: Any, tmp_path: Path) -> None:
    import yaml
    from helpers import API, admin, code, wait_job

    admin(client)
    client.post(f"{API}/zones", json={"name": "Jeux", "color": "#d97706", "network_mode": "shared"})
    client.post(f"{API}/zones", json={"name": "Solo", "color": "#65a30d"})
    body = {"template": "wireguard", "name": "vpn", "inputs": {"host": "vpn.example.org"}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    assert client.get(f"{API}/apps/{app_id}").json()["vpn"] is True
    runtime = client.app.state.runtime
    conf = runtime.settings.volumes_root / "vpn" / "config" / "wg_confs" / "wg0.conf"

    # Stopped: the config is written anyway, the image brings it up on start.
    phone = client.post(f"{API}/apps/{app_id}/vpn/clients", json={"name": "phone"}).json()["id"]
    assert "AllowedIPs = 10.8.0.2/32" in conf.read_text() and conf.stat().st_mode & 0o077 == 0

    gw = runtime.gateway
    gw.put(ContainerInfo(
        id="wg1", name="vpn-server-1", image="wg", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "vpn", "com.docker.compose.service": "server"},
    ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while runtime.state.store.app("vpn").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)

    # The exec into WireGuard runs with the database free: other requests can write.
    from sqlalchemy import text as sql

    real_exec, writes = gw.exec_run, []

    async def exec_while_writing(cid: str, cmd: list[str], user: str | None = None) -> Any:
        async with runtime.sessions() as s, s.begin():
            await s.execute(sql("UPDATE vpn_peer SET name = name"))
        writes.append(cmd[0])
        return await real_exec(cid, cmd, user)

    gw.exec_run = exec_while_writing
    # First start without a config: the image dropped the default route, put it back.
    gw.networks.append(
        NetworkInfo("n1", "vpn_default", "bridge", False, subnets=("172.31.0.0/16",))
    )
    laptop = client.post(
        f"{API}/apps/{app_id}/vpn/clients",
        json={"name": "laptop", "allowed_ips": ["192.168.1.0/24"]},
    ).json()["id"]
    assert gw.exec_calls[-1][:2] == ["sh", "-c"] and "wg syncconf wg0" in gw.exec_calls[-1][2]
    restore = "ip -4 route show default | grep -q . || ip route add default via 172.31.0.1; "
    assert f"else {restore}wg-quick up" in gw.exec_calls[-1][2]
    gw.exec_run = real_exec
    assert writes == ["sh"]
    cfg = client.get(f"{API}/apps/{app_id}/vpn/clients/{laptop}/config").text
    assert "Endpoint = vpn.example.org:51820" in cfg and "AllowedIPs = 192.168.1.0/24" in cfg
    assert "Address = 10.8.0.3/32" in cfg and "DNS = 10.8.0.1\n" in cfg  # the VPN's own DNS
    psk = next(line for line in cfg.splitlines() if line.startswith("PresharedKey = "))
    assert len(psk.split(" = ")[1]) == 44 and psk in conf.read_text()  # both ends agree
    qr = client.get(f"{API}/apps/{app_id}/vpn/clients/{laptop}/qrcode")
    assert qr.status_code == 200 and qr.text.startswith("<svg")

    old_key = client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][1]["public_key"]
    assert client.post(f"{API}/apps/{app_id}/vpn/clients/{laptop}/renew").json()["id"] == laptop
    after = client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][1]
    assert after["public_key"] != old_key and after["allowed_ips"] == ["192.168.1.0/24"]

    client.put(f"{API}/apps/{app_id}/vpn/clients/{phone}", json={"enabled": False})
    assert "# phone" not in conf.read_text() and "# laptop" in conf.read_text()
    assert client.delete(f"{API}/apps/{app_id}/vpn/clients/{phone}").status_code == 204
    gone = client.get(f"{API}/apps/{app_id}/vpn/clients/{phone}/config")
    assert gone.status_code == 404 and code(gone) == "vpn_client_not_found"

    gw.exec_results["sh -c " + gw.exec_calls[-1][2]] = (
        1,
        "RTNETLINK answers: Operation not permitted",
    )
    failed = client.post(f"{API}/apps/{app_id}/vpn/clients", json={"name": "tablet"})
    assert failed.status_code == 409 and code(failed) == "vpn_apply_failed"
    names = [c["name"] for c in client.get(f"{API}/apps/{app_id}/vpn").json()["clients"]]
    assert names == ["laptop"]  # rolled back

    job = client.put(f"{API}/apps/{app_id}/vpn/zones", json={"zones": ["jeux"]}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    assert compose["networks"]["reach0"] == {"name": "hivora-zone-jeux", "external": True}
    assert client.get(f"{API}/apps/{app_id}/vpn").json()["zones"] == ["jeux"]
    # A zone whose apps had no network of their own: linked by the VPN, it gets one.
    job = client.put(f"{API}/apps/{app_id}/vpn/zones", json={"zones": ["jeux", "solo"]}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    zones = {z["slug"]: z for z in client.get(f"{API}/zones").json()}
    assert (zones["solo"]["network_mode"], zones["solo"]["vpn"]) == ("shared", "vpn")
    assert zones["solo"]["vpn_slug"] == "vpn"  # its DNS, from the dashboard
    assert (zones["jeux"]["subnet"], zones["solo"]["subnet"]) == ("10.8.1.0/24", "10.8.2.0/24")

    # Addressing: a client picks its IP, then a new network renumbers what no longer fits.
    gw.exec_results.clear()
    moved = client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json={"address": "10.8.0.50"})
    assert moved.status_code == 204 and "AllowedIPs = 10.8.0.50/32" in conf.read_text()
    taken = client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json={"address": "10.8.0.1"})
    assert taken.status_code == 422 and code(taken) == "vpn_bad_address"
    settings = client.get(f"{API}/apps/{app_id}/settings").json()["values"]
    new_net = {**settings, "vpn_subnet": "10.9.0.0/24", "vpn_server_ip": "10.9.0.254",
               "vpn_port": 51999}  # fmt: skip
    job = client.put(f"{API}/apps/{app_id}/settings", json={"inputs": new_net}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    vpn = client.get(f"{API}/apps/{app_id}/vpn").json()
    assert (vpn["subnet"], vpn["server_address"]) == ("10.9.0.0/24", "10.9.0.254")
    assert vpn["clients"][0]["address"] == "10.9.0.1"
    text = conf.read_text()
    assert "Address = 10.9.0.254/24" in text and "-s 10.9.0.0/24 -j MASQUERADE" in text
    cfg = client.get(f"{API}/apps/{app_id}/vpn/clients/{laptop}/config").text
    assert "Endpoint = vpn.example.org:51999" in cfg

    # Access rights, routing preset, rename, expiry.
    from dataclasses import replace
    from datetime import timedelta

    gw.networks = [replace(n, subnets=("172.30.0.0/16",)) if n.name == "hivora-zone-jeux" else n
                   for n in gw.networks]  # fmt: skip
    acl = conf.parent.parent / "hivora-acl.sh"
    change = {"name": "portable", "routing": "access",
              "access": {"internet": False, "lan": False, "zones": ["jeux"]}}  # fmt: skip
    assert client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json=change).status_code == 204
    row = client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][0]
    assert row["name"] == "portable" and row["access"]["zones"] == ["jeux"]
    assert "-s 10.9.0.1/32 -d 172.30.0.0/16 -j ACCEPT" in acl.read_text()
    assert "-s 10.9.0.1/32 -j DROP" in acl.read_text() and "sh /config/hivora-acl.sh" in text
    cfg = client.get(f"{API}/apps/{app_id}/vpn/clients/{laptop}/config").text
    assert "AllowedIPs = 10.9.0.0/24, 172.30.0.0/16" in cfg

    soon = (runtime.clock.now() + timedelta(hours=1)).isoformat()
    client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json={"expires_at": soon})
    assert client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][0]["active"] is True
    past = (runtime.clock.now() - timedelta(minutes=1)).isoformat()
    client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json={"expires_at": past})
    row = client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][0]
    assert row["active"] is False and "# portable" not in conf.read_text()
    client.put(f"{API}/apps/{app_id}/vpn/clients/{laptop}", json={"enabled": True})
    row = client.get(f"{API}/apps/{app_id}/vpn").json()["clients"][0]
    assert row["active"] is True and row["expires_at"] is None  # re-enabled by hand


def test_a_vpn_deployed_for_a_new_zone_serves_it(client: Any) -> None:
    from helpers import API, admin, wait_job

    admin(client)
    client.post(f"{API}/zones", json={"name": "Maison", "color": "#d97706"})
    body = {"template": "wireguard", "name": "vpn maison", "inputs": {"host": "vpn.example.org"},
            "vpn_zones": ["maison"]}  # fmt: skip
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    zone = next(z for z in client.get(f"{API}/zones").json() if z["slug"] == "maison")
    served = (zone["vpn"], zone["network_mode"], zone["subnet"])
    assert served == ("vpn maison", "shared", "10.8.1.0/24")
    assert client.get(f"{API}/apps/{deployed['app']['id']}/vpn").json()["zones"] == ["maison"]


def test_vpn_local_dns_names(client: Any) -> None:
    """Names of the VPN: to an IP, or to an app of its zones (its container, through Docker)."""
    from helpers import API, admin, code, wait_job

    admin(client)
    client.post(f"{API}/zones", json={"name": "Jeux", "color": "#d97706"})
    body = {"template": "wireguard", "name": "vpn", "inputs": {"host": "vpn.example.org"},
            "vpn_zones": ["jeux"]}  # fmt: skip
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    vpn_id = deployed["app"]["id"]
    ids = []
    for name, zone in (("web", "jeux"), ("ailleurs", None)):
        app = client.post(f"{API}/apps", json={"template": "nginx", "name": name, "zone": zone})
        assert wait_job(client, app.json()["job"]["id"])["status"] == "succeeded"
        ids.append(app.json()["app"]["id"])
    web, other = ids
    dns = client.get(f"{API}/apps/{vpn_id}/vpn/dns").json()
    assert (dns["enabled"], dns["server"]) == (True, "10.8.0.1")
    assert [t["id"] for t in dns["targets"]] == [web]  # only the apps of its zones

    url = f"{API}/apps/{vpn_id}/vpn/dns"
    assert client.post(url, json={"name": "Web.Local", "app_id": web}).status_code == 201
    assert client.post(url, json={"name": "nas.local", "ip": "192.168.1.20"}).status_code == 201
    for bad, status, err in (
        ({"name": "web.local", "ip": "192.168.1.21"}, 409, "vpn_dns_name_taken"),
        ({"name": "x.local", "app_id": other}, 409, "vpn_dns_bad_target"),
        ({"name": "x.local", "ip": "999.1.1.1"}, 409, "vpn_dns_bad_target"),
        ({"name": "x.local", "app_id": web, "ip": "1.2.3.4"}, 409, "vpn_dns_bad_target"),
        ({"name": "x.local", "port": 80}, 409, "vpn_dns_bad_target"),  # a port needs its app
        (
            {"name": "x.local", "app_id": web, "service": "server", "port": 9},
            409,
            "vpn_dns_bad_target",
        ),  # no such port
        ({"name": "x local; }", "ip": "1.2.3.4"}, 422, "vpn_dns_bad_name"),
    ):
        r = client.post(url, json=bad)
        assert (r.status_code, code(r)) == (status, err), bad
    records = client.get(url).json()["records"]
    assert [(r["name"], r["ip"], r["app_name"]) for r in records] == [
        ("nas.local", "192.168.1.20", None), ("web.local", None, "web")]  # fmt: skip

    runtime = client.app.state.runtime
    corefile = runtime.settings.volumes_root / "vpn" / "config" / "coredns" / "Corefile"
    text = corefile.read_text()
    assert "        192.168.1.20 nas.local\n" in text
    assert "    forward . /etc/resolv.conf\n" in text  # Internet: the machine's DNS
    assert "rewrite continue name exact web.local. web-server-1. answer auto" in text
    assert client.delete(f"{url}/{records[0]['id']}").status_code == 204
    assert "nas.local" not in corefile.read_text()
