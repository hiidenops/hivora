"""The admin VPN (vpn modes): set up once on start, protected, rescued from the machine."""

import base64
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from helpers import API, STRONG, code, login, wait_job
from pydantic import ValidationError

from hivora.core.config import Settings
from hivora.docker_gateway import NetworkInfo
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.vpn.admin import ADMIN_VPN_SUBNET, ADMIN_ZONE_SUBNET

FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]
SLUG = "admin-vpn"


def settings_for(tmp_path: Path, access: str, **launch: Any) -> Settings:
    """``launch``: what the installer passes (admin_vpn_host, admin_vpn_port)."""
    return Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                    catalog_dir=Path(__file__).parents[2] / "templates", access=access,  # type: ignore[arg-type]
                    dev_insecure_cookies=True, puid=os.getuid(), pgid=os.getgid(),
                    host_lan_ip="192.168.1.10", host_public_ip="203.0.113.7", **launch)  # fmt: skip


@contextmanager
def panel(tmp_path: Path, access: str = "vpn", **launch: Any) -> Iterator[TestClient]:
    """The server on this data folder; in a vpn mode, once the admin VPN is in line."""
    gateway = FakeDockerGateway()
    # As the installer creates it (M12-5b): the zone's network with its fixed subnet.
    gateway.networks.append(NetworkInfo(id="adm", name="hivora-zone-administration",
                                        driver="bridge", internal=False, labels={},
                                        subnets=(ADMIN_ZONE_SUBNET,)))  # fmt: skip
    runtime = Runtime.build(settings_for(tmp_path, access, **launch), gateway=gateway,
                            compose_cmd=FAKE)  # fmt: skip
    runtime.admin_vpn.poll_s = 0.05
    with TestClient(create_app(runtime=runtime)) as c:
        deadline = time.monotonic() + 15
        task = next(t for t in runtime._vpn_tasks if t.get_name() == "admin-vpn")
        while not task.done():  # in line (vpn modes), or nothing to do (other modes)
            assert time.monotonic() < deadline, "admin VPN not set up"
            time.sleep(0.02)
        if not login_once(c):
            login(c, "admin", STRONG)
        yield c


def login_once(c: TestClient) -> bool:
    """First start: admin/admin, then the password changed; later starts: False."""
    r = c.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"})
    if r.status_code != 200:
        return False
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    c.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG})
    return True


def db(tmp_path: Path, query: str) -> list[Any]:
    with closing(sqlite3.connect(tmp_path / "data" / "hivora.db")) as conn:
        return conn.execute(query).fetchall()


def state(tmp_path: Path) -> dict[str, Any] | None:
    import json

    rows = db(tmp_path, "SELECT value FROM setting WHERE key = 'vpn.admin'")
    return json.loads(rows[0][0]) if rows else None


def conf(tmp_path: Path) -> Path:
    return tmp_path / "data" / "admin.conf"


def fields(text: str) -> dict[str, list[str]]:
    """A WireGuard file's ``Key = value`` lines, by key (in order)."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            out.setdefault(key, []).append(value)
    return out


def public_of(private: str) -> str:
    key = X25519PrivateKey.from_private_bytes(base64.b64decode(private))
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()


def test_settings_and_lan_mode_create_nothing(tmp_path: Path) -> None:
    assert Settings().admin_vpn_port == 51820 and Settings().admin_vpn_host is None
    with pytest.raises(ValidationError):
        Settings(admin_vpn_port=70000)
    with panel(tmp_path, "lan") as c:
        assert c.get(f"{API}/apps").json() == []
        zone = next(z for z in c.get(f"{API}/zones").json() if z["slug"] == "administration")
        assert zone["network_mode"] == "none"
    assert state(tmp_path) is None and not conf(tmp_path).exists()


def test_first_start_sets_the_admin_vpn_up(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        apps = c.get(f"{API}/apps").json()
        zone = next(z for z in c.get(f"{API}/zones").json() if z["slug"] == "administration")
        assert [(a["slug"], a["zone_id"]) for a in apps] == [(SLUG, zone["id"])]
        assert zone["network_mode"] == "shared"
        values = c.get(f"{API}/apps/{apps[0]['id']}/settings").json()["values"]
        assert values["vpn_subnet"] == ADMIN_VPN_SUBNET and values["vpn_zones"] == "administration"
        assert values["host"] == "203.0.113.7" and values["vpn_port"] == 51820
        vpn = c.get(f"{API}/apps/{apps[0]['id']}/vpn").json()
        [client] = vpn["clients"]
        assert client["name"] == "admin" and client["protected"] is True
        assert client["access"] == {"internet": False, "lan": False, "zones": ["administration"]}
        assert client["routing"] == "access" and client["enabled"] is True
    s = state(tmp_path)
    assert s is not None and s["app_id"] == apps[0]["id"] and s["client_id"] == client["id"]
    assert s["initialized_at"]
    assert conf(tmp_path).stat().st_mode & 0o777 == 0o600


def test_admin_conf_is_a_valid_client_of_the_server(tmp_path: Path) -> None:
    with panel(tmp_path):
        pass
    client = fields(conf(tmp_path).read_text())
    server = fields((tmp_path / "srv" / SLUG / "config" / "wg_confs" / "wg0.conf").read_text())
    [private], [address] = client["PrivateKey"], client["Address"]
    assert len(base64.b64decode(private)) == 32
    assert server["PublicKey"] == [public_of(private)]  # the server knows this client
    assert client["PublicKey"] == [public_of(server["PrivateKey"][0])]  # and the client it
    assert client["PresharedKey"] == server["PresharedKey"]
    assert server["AllowedIPs"] == [address]
    assert address.endswith("/32") and address.startswith("10.254.253.")
    assert client["AllowedIPs"] == [f"{ADMIN_VPN_SUBNET}, {ADMIN_ZONE_SUBNET}"]  # zone only
    assert client["Endpoint"] == ["203.0.113.7:51820"] and client["DNS"]
    assert "[Interface]" in conf(tmp_path).read_text() and "0.0.0.0/0" not in str(client)


def test_starting_again_creates_nothing_twice(tmp_path: Path) -> None:
    with panel(tmp_path):
        pass
    first, text = state(tmp_path), conf(tmp_path).read_text()
    for _ in range(2):
        with panel(tmp_path) as c:
            assert [a["slug"] for a in c.get(f"{API}/apps").json()] == [SLUG]
    assert state(tmp_path) == first and conf(tmp_path).read_text() == text  # same keys
    assert db(tmp_path, "SELECT count(*) FROM vpn_peer WHERE server = 0") == [(1,)]
    assert db(tmp_path, "SELECT count(*) FROM job WHERE kind = 'deploy'") == [(1,)]


def test_the_admin_vpn_is_protected_in_the_vpn_modes(tmp_path: Path) -> None:
    with panel(tmp_path, "vpn+lan") as c:
        s = state(tmp_path)
        assert s is not None
        app, cid = s["app_id"], s["client_id"]
        clients = f"{API}/apps/{app}/vpn/clients"
        expiry = {"expires_at": "2030-01-01T00:00:00Z"}
        for r in (c.delete(f"{API}/apps/{app}"), c.delete(f"{clients}/{cid}"),
                  c.put(f"{clients}/{cid}", json={"enabled": False}),
                  c.put(f"{clients}/{cid}", json=expiry)):  # fmt: skip
            assert r.status_code == 409 and code(r) == "admin_vpn_protected", r.text
        assert c.put(f"{clients}/{cid}", json={"name": "admin-laptop"}).status_code == 204
        other = c.post(clients, json={"name": "phone"}).json()["id"]
        assert c.put(f"{clients}/{other}", json={"enabled": False}).status_code == 204
        assert c.delete(f"{clients}/{other}").status_code == 204
        [client] = c.get(f"{API}/apps/{app}/vpn").json()["clients"]
        assert client["enabled"] is True and client["expires_at"] is None
    with panel(tmp_path, "lan") as c:  # back to the LAN only: it can go
        [client] = c.get(f"{API}/apps/{app}/vpn").json()["clients"]
        assert client["protected"] is False
        assert c.delete(f"{clients}/{cid}").status_code == 204
        removed = c.delete(f"{API}/apps/{app}")
        assert removed.status_code == 202
        assert wait_job(c, removed.json()["id"])["status"] == "succeeded"
        assert c.get(f"{API}/apps").json() == []
    with panel(tmp_path) as c:  # VPN again: set up anew
        [new] = c.get(f"{API}/apps").json()
        again = state(tmp_path)
        assert again is not None and again["app_id"] == new["id"]
        assert again["initialized_at"] != s["initialized_at"]
        [client] = c.get(f"{API}/apps/{new['id']}/vpn").json()["clients"]
        assert client["protected"] is True and again["client_id"] == client["id"]


def test_new_keys_reach_admin_conf(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        s = state(tmp_path)
        assert s is not None
        before = conf(tmp_path).read_text()
        r = c.post(f"{API}/apps/{s['app_id']}/vpn/clients/{s['client_id']}/renew")
        assert r.status_code == 200
        deadline = time.monotonic() + 5
        while conf(tmp_path).read_text() == before:
            assert time.monotonic() < deadline, "admin.conf did not follow"
            time.sleep(0.02)
        key = c.get(f"{API}/apps/{s['app_id']}/vpn").json()["clients"][0]["public_key"]
        assert public_of(fields(conf(tmp_path).read_text())["PrivateKey"][0]) == key


def run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HIVORA_DATA_DIR": str(tmp_path / "data")}
    return subprocess.run([sys.executable, "-m", "hivora", *args], env=env,  # noqa: S603
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


def test_rescue_admin_gives_new_keys_at_the_next_start(tmp_path: Path) -> None:
    with panel(tmp_path):
        s = state(tmp_path)
        assert s is not None
    old = fields(conf(tmp_path).read_text())["PrivateKey"][0]
    db_conn = sqlite3.connect(tmp_path / "data" / "hivora.db")
    with closing(db_conn), db_conn:  # lost access: disabled by hand in the database
        db_conn.execute("UPDATE vpn_peer SET enabled = 0 WHERE server = 0")
    done = run(tmp_path, "rescue-admin")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["ADMIN_VPN=rescue_requested"]
    assert db(tmp_path, "SELECT count(*) FROM setting WHERE key = 'vpn.admin_rescue'") == [(1,)]
    with panel(tmp_path) as c:
        [client] = c.get(f"{API}/apps/{s['app_id']}/vpn").json()["clients"]
        assert client["enabled"] is True and client["id"] == s["client_id"]
    new = fields(conf(tmp_path).read_text())["PrivateKey"][0]
    assert new != old and public_of(new) == client["public_key"]
    assert db(tmp_path, "SELECT count(*) FROM setting WHERE key = 'vpn.admin_rescue'") == [(0,)]


def test_admin_vpn_command_shows_the_file_and_its_qr_code(tmp_path: Path) -> None:
    missing = run(tmp_path, "admin-vpn")
    assert missing.returncode == 1 and "error:" in missing.stderr and missing.stdout == ""
    with panel(tmp_path):
        pass
    done = run(tmp_path, "admin-vpn")
    assert done.returncode == 0, done.stderr
    first, *qr = done.stdout.splitlines()
    assert first == f"ADMIN_CONF={conf(tmp_path)}"
    assert len(qr) > 20 and any("█" in line or "▀" in line for line in qr)
    assert "PrivateKey" not in done.stdout  # the key is in the code, not printed in clear


def test_admin_login_still_works_and_nothing_secret_is_audited(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        deadline = time.monotonic() + 5  # the audit is written in batches (0.5 s)
        while "vpn.client_created" not in c.get(f"{API}/audit").text:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        time.sleep(1)  # the next batch too
        admin_events = [e["action"] for e in c.get(f"{API}/audit").json()]
        assert "vpn.config_downloaded" not in admin_events  # written by Hivora, not downloaded
        private = fields(conf(tmp_path).read_text())["PrivateKey"][0]
        assert private not in c.get(f"{API}/audit").text


def test_apps_already_in_the_zone_join_its_network(tmp_path: Path) -> None:
    with panel(tmp_path, "lan") as c:
        body = {"template": "nginx", "name": "Tools", "zone": "administration",
                "inputs": {"web_port": 8190}}  # fmt: skip
        deployed = c.post(f"{API}/apps", json=body).json()
        assert wait_job(c, deployed["job"]["id"])["status"] == "succeeded"
        tools = deployed["app"]["id"]
    with panel(tmp_path) as c:
        compose = c.get(f"{API}/apps/{tools}/compose").json()["compose_yaml"]
        assert "hivora-zone-administration" in compose  # a new revision, on the shared network
        assert sorted(a["slug"] for a in c.get(f"{API}/apps").json()) == [SLUG, "tools"]


def test_a_taken_port_leaves_the_panel_up_and_retries_at_the_next_start(tmp_path: Path) -> None:
    with panel(tmp_path, "lan") as c:
        body = {"template": "wireguard", "name": "Home", "inputs": {"host": "vpn.example.org"}}
        deployed = c.post(f"{API}/apps", json=body).json()  # 51820/udp: the user's own VPN
        assert wait_job(c, deployed["job"]["id"])["status"] == "succeeded"
    with panel(tmp_path) as c:
        assert c.get(f"{API}/system/health").status_code == 200
        assert [a["slug"] for a in c.get(f"{API}/apps").json()] == ["home"]
    assert state(tmp_path) is None and not conf(tmp_path).exists()
    with panel(tmp_path, "lan") as c:
        removed = c.delete(f"{API}/apps/{deployed['app']['id']}").json()
        assert wait_job(c, removed["id"])["status"] == "succeeded"
    with panel(tmp_path):  # the port is free now
        pass
    assert (state(tmp_path) or {}).get("initialized_at") and conf(tmp_path).exists()


def test_the_certificate_names_the_panel_vpn_address(tmp_path: Path) -> None:
    from hivora.__main__ import cert_names
    from hivora.vpn.admin import PANEL_IP

    assert PANEL_IP in cert_names(settings_for(tmp_path, "vpn+lan"))
    assert PANEL_IP in cert_names(settings_for(tmp_path, "vpn"))
    assert PANEL_IP not in cert_names(settings_for(tmp_path, "lan"))


# --- M12-5d: install.env sets the admin VPN's address and port (D17) ----------------------
def endpoint(tmp_path: Path) -> str:
    return fields(conf(tmp_path).read_text())["Endpoint"][0]


def revisions(tmp_path: Path) -> int:
    return int(db(tmp_path, "SELECT count(*) FROM app_revision")[0][0])


def keys(tmp_path: Path) -> tuple[str, str]:
    """(the client's private key, the server's private key): what must never change here."""
    server = (tmp_path / "srv" / SLUG / "config" / "wg_confs" / "wg0.conf").read_text()
    return fields(conf(tmp_path).read_text())["PrivateKey"][0], fields(server)["PrivateKey"][0]


def test_a_new_address_reaches_the_app_and_admin_conf(tmp_path: Path) -> None:
    with panel(tmp_path, admin_vpn_host="82.64.12.34"):
        pass
    assert endpoint(tmp_path) == "82.64.12.34:51820"
    before, count = keys(tmp_path), revisions(tmp_path)
    with panel(tmp_path, admin_vpn_host="home.example.org") as c:
        s = state(tmp_path)
        assert s is not None
        values = c.get(f"{API}/apps/{s['app_id']}/settings").json()["values"]
        assert values["host"] == "home.example.org"
    assert endpoint(tmp_path) == "home.example.org:51820"
    assert keys(tmp_path) == before and revisions(tmp_path) == count + 1  # only the endpoint
    with panel(tmp_path, admin_vpn_host="home.example.org"):  # the same again: nothing
        pass
    assert revisions(tmp_path) == count + 1 and state(tmp_path) == s


def test_a_new_port_reaches_the_app_and_admin_conf(tmp_path: Path) -> None:
    with panel(tmp_path, admin_vpn_port=51820):
        pass
    before = keys(tmp_path)
    with panel(tmp_path, admin_vpn_port=51830) as c:
        s = state(tmp_path)
        assert s is not None
        compose = c.get(f"{API}/apps/{s['app_id']}/compose").json()["compose_yaml"]
        assert "51830" in compose and "51820:" not in compose  # published on the new port
    assert endpoint(tmp_path) == "203.0.113.7:51830" and keys(tmp_path) == before


def test_nothing_is_aligned_unless_install_env_sets_it(tmp_path: Path) -> None:
    with panel(tmp_path, admin_vpn_host="82.64.12.34", admin_vpn_port=51830):
        pass
    count = revisions(tmp_path)
    with panel(tmp_path):  # launched by hand: no address, no explicit port (51820 by default)
        pass
    assert revisions(tmp_path) == count and endpoint(tmp_path) == "82.64.12.34:51830"
    with panel(tmp_path, "lan", admin_vpn_host="other.example.org", admin_vpn_port=51840):
        pass  # not a vpn mode
    assert revisions(tmp_path) == count and endpoint(tmp_path) == "82.64.12.34:51830"


def test_a_taken_port_keeps_the_old_one_and_the_panel_up(tmp_path: Path) -> None:
    with panel(tmp_path):
        pass
    with panel(tmp_path, "lan") as c:  # the user's own VPN on 51830
        body = {"template": "wireguard", "name": "Home",
                "inputs": {"host": "vpn.example.org", "vpn_port": 51830}}  # fmt: skip
        deployed = c.post(f"{API}/apps", json=body).json()
        assert wait_job(c, deployed["job"]["id"])["status"] == "succeeded"
    count, key = revisions(tmp_path), keys(tmp_path)[0]
    assert run(tmp_path, "rescue-admin").returncode == 0  # asked meanwhile: still done
    with panel(tmp_path, admin_vpn_port=51830) as c:
        assert c.get(f"{API}/system/health").status_code == 200
    assert revisions(tmp_path) == count and endpoint(tmp_path) == "203.0.113.7:51820"
    assert keys(tmp_path)[0] != key  # the rest of the setup went on: new keys, admin.conf
    assert db(tmp_path, "SELECT count(*) FROM setting WHERE key = 'vpn.admin_rescue'") == [(0,)]


def test_the_panel_cannot_change_what_install_env_sets(tmp_path: Path) -> None:
    with panel(tmp_path, admin_vpn_host="82.64.12.34", admin_vpn_port=51820) as c:
        s = state(tmp_path)
        assert s is not None
        url = f"{API}/apps/{s['app_id']}/settings"
        values = c.get(url).json()["values"]
        for field, value in (("host", "other.example.org"), ("vpn_port", 51850)):
            r = c.put(url, json={"inputs": {**values, field: value}})
            assert r.status_code == 409 and code(r) == "admin_vpn_managed", field
        r = c.put(url, json={"inputs": {**values, "dns": "9.9.9.9"}})  # not set by it: free
        assert r.status_code == 202, r.text
        assert wait_job(c, r.json()["id"])["status"] == "succeeded"
    with panel(tmp_path) as c:  # no address in install.env: the panel may change it
        values = c.get(url).json()["values"]
        r = c.put(url, json={"inputs": {**values, "host": "other.example.org"}})
        assert r.status_code == 202, r.text


def test_the_system_page_reports_the_admin_vpn_without_its_keys(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        r = c.get(f"{API}/system/status")
        assert r.status_code == 200, r.text
        vpn = next(x for x in r.json()["checks"] if x["id"] == "admin_vpn")
        # The fake Docker runs nothing: set up, admin.conf there, the container not running.
        assert vpn["values"] == {"initialized": True, "conf": True, "running": False}
        assert vpn["level"] == "warn" and r.json()["access"] == "vpn"
        for secret in keys(tmp_path):
            assert secret not in r.text
