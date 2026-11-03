import time
from datetime import UTC, datetime, timedelta
from typing import Any

from hivora.docker_gateway import ContainerInfo, ContainerState


def _cert(path: Any, domain: str, until: datetime) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, domain)])
    issuer = x509.Name([x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Let's Encrypt")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(until - timedelta(days=90)).not_valid_after(until)
            .sign(key, hashes.SHA256()))  # fmt: skip
    path.mkdir(parents=True)
    (path / f"{domain}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def test_public_domains_through_the_https_proxy(client: Any) -> None:
    import yaml
    from helpers import API, admin, code, wait_job

    admin(client)
    runtime = client.app.state.runtime
    seen: list[str] = []

    async def resolver(domain: str) -> list[str]:
        seen.append(domain)
        return ["203.0.113.7"] if domain == "cloud.example.org" else []

    runtime.proxy.resolver = resolver
    runtime.proxy.public_ip = lambda: "203.0.113.7"
    url = f"{API}/proxy"
    assert client.get(url).json()["installed"] is False
    for name in ("Web", "Jeux"):
        client.post(f"{API}/zones", json={"name": name, "color": "#d97706"})
    vpn = {"template": "wireguard", "name": "vpn", "inputs": {"host": "vpn.example.org"},
           "vpn_zones": ["jeux"]}  # fmt: skip
    ids = {}
    for name, body in (
        ("vpn", vpn),
        ("site", {"template": "nginx", "name": "site", "zone": "web"}),
        ("cache", {"template": "nginx", "name": "cache", "zone": "jeux"}),
    ):
        r = client.post(f"{API}/apps", json=body).json()
        assert wait_job(client, r["job"]["id"])["status"] == "succeeded"
        ids[name] = r["app"]["id"]
    no_proxy = client.post(f"{url}/routes", json={"domain": "cloud.example.org",
                                                  "app_id": ids["site"]})  # fmt: skip
    assert (no_proxy.status_code, code(no_proxy)) == (409, "proxy_not_installed")

    r = client.post(f"{API}/apps", json={"template": "caddy", "name": "proxy"}).json()
    assert wait_job(client, r["job"]["id"])["status"] == "succeeded"
    proxy_id = r["app"]["id"]
    out = client.get(url).json()
    assert (out["installed"], out["app_id"]) == (True, proxy_id)
    assert [t["id"] for t in out["targets"]] == [ids["site"]]  # not behind the VPN

    for bad, status, err in (
        ({"domain": "site.local", "app_id": ids["site"]}, 422, "proxy_bad_domain"),
        ({"domain": "cache.example.org", "app_id": ids["cache"]}, 409, "proxy_bad_target"),
    ):
        r = client.post(f"{url}/routes", json=bad)
        assert (r.status_code, code(r)) == (status, err), bad
    created = client.post(f"{url}/routes", json={"domain": "Cloud.Example.org",
                                                 "app_id": ids["site"]}).json()  # fmt: skip
    assert created["job"] is not None  # the proxy joins the zone's network first
    assert wait_job(client, created["job"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{proxy_id}/compose").json()["compose_yaml"])
    assert {"name": "hivora-zone-web", "external": True} in compose["networks"].values()
    zones = {z["slug"]: z for z in client.get(f"{API}/zones").json()}
    assert zones["web"]["network_mode"] == "shared"
    dup = client.post(f"{url}/routes", json={"domain": "cloud.example.org", "app_id": ids["site"]})
    assert (dup.status_code, code(dup)) == (409, "proxy_domain_taken")

    # Running: the sites file follows (the deploy's event), Caddy is reloaded.
    gw = runtime.gateway
    gw.put(ContainerInfo(
        id="caddy1", name="proxy-server-1", image="caddy", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "proxy", "com.docker.compose.service": "server"},
    ), "start")  # fmt: skip
    deadline = time.monotonic() + 3
    while runtime.state.store.app("proxy").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    sites = runtime.settings.volumes_root / "proxy" / "conf" / "sites.caddy"
    second = client.post(f"{url}/routes", json={"domain": "www.example.org",
                                                "app_id": ids["site"]}).json()  # fmt: skip
    assert second["job"] is None  # same zone: served at once
    text = sites.read_text()
    assert "cloud.example.org {\n    reverse_proxy site-server-1:80\n}" in text
    assert "www.example.org {" in text
    assert gw.exec_calls[-1] == ["caddy", "reload", "--config", "/etc/caddy/Caddyfile"]

    # Certificates: one obtained, one refused by Let's Encrypt (Caddy's log).
    data = runtime.settings.volumes_root / "proxy" / "data" / "caddy" / "certificates"
    until = datetime.now(UTC) + timedelta(days=60)
    _cert(data / "acme-v02.api.letsencrypt.org-directory" / "cloud.example.org",
          "cloud.example.org", until)  # fmt: skip
    gw.logs_by_container["caddy1"] = [
        '{"level":"error","logger":"tls.obtain","msg":"could not get certificate from issuer",'
        '"identifier":"www.example.org","error":"HTTP 400 urn:ietf:params:acme:error:dns"}'
    ]
    routes = {r["domain"]: r for r in client.get(url).json()["routes"]}
    ok, refused = routes["cloud.example.org"], routes["www.example.org"]
    assert (ok["status"], ok["issuer"], ok["points_here"]) == ("valid", "Let's Encrypt", True)
    assert (refused["status"], refused["points_here"]) == ("error", False)
    assert "acme:error:dns" in refused["error"] and refused["dns"] == []

    assert client.delete(f"{url}/routes/{refused['id']}").status_code == 204
    assert "www.example.org" not in sites.read_text()
