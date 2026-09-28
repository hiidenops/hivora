import time
from pathlib import Path
from typing import Any

from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.vpn import wireguard as wg


def test_keys_configs_and_dump() -> None:
    private, public = wg.keypair()
    assert len(private) == len(public) == 44 and wg.public_of(private) == public

    peers = [wg.Peer("phone", "10.8.0.2", "PUB2")]
    conf = wg.server_conf("PRIV", "10.8.0.0/24", 51820, "wg0", peers)
    assert "Address = 10.8.0.1/24" in conf and "ListenPort = 51820" in conf
    assert "-s 10.8.0.0/24 -j MASQUERADE" in conf  # every interface: LAN and zone networks
    assert "# phone\n[Peer]\nPublicKey = PUB2\nAllowedIPs = 10.8.0.2/32" in conf

    assert wg.free_address("10.8.0.0/24", {"10.8.0.1", "10.8.0.2"}) == "10.8.0.3"
    assert wg.free_address("10.8.0.0/30", {"10.8.0.1", "10.8.0.2"}) is None

    dump = "PRIV\tPUB\t51820\toff\nPUB2\t(none)\t1.2.3.4:5\t10.8.0.2/32\t1700000000\t10\t20\t25\n"
    stats = wg.parse_dump(dump)["PUB2"]
    assert (stats.rx, stats.tx) == (10, 20) and stats.latest_handshake.startswith("2023-11-14")
    assert (
        wg.parse_dump("PRIV\tPUB\t51820\toff\nP3\t(none)\t(none)\t10.8.0.3/32\t0\t0\t0\toff\n")[
            "P3"
        ].latest_handshake
        is None
    )


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
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
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

    laptop = client.post(
        f"{API}/apps/{app_id}/vpn/clients",
        json={"name": "laptop", "allowed_ips": ["192.168.1.0/24"]},
    ).json()["id"]
    assert gw.exec_calls[-1][:2] == ["sh", "-c"] and "wg syncconf wg0" in gw.exec_calls[-1][2]
    cfg = client.get(f"{API}/apps/{app_id}/vpn/clients/{laptop}/config").text
    assert "Endpoint = vpn.example.org:51820" in cfg and "AllowedIPs = 192.168.1.0/24" in cfg
    assert "Address = 10.8.0.3/32" in cfg and "DNS = 1.1.1.1,9.9.9.9" in cfg
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
    refused = client.put(f"{API}/apps/{app_id}/vpn/zones", json={"zones": ["solo"]})
    assert refused.status_code == 422
