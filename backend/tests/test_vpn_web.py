"""The VPN's web proxy: a name aimed at a web port other than 80 opens without its port."""

from typing import Any

from helpers import API, admin, code, nginx_host, wait_job

from hivora.vpn import web


def test_which_names_go_through_the_proxy() -> None:
    assert not web.via_proxy(None) and not web.via_proxy(80) and web.via_proxy(8081)
    text = web.sites([web.Route("blog.lan", "vitrine-server-1", 8081, "hivora-zone-jeux")])
    assert "http://blog.lan {\n    reverse_proxy vitrine-server-1:8081\n}" in text


def test_the_proxy_image_is_the_https_proxys(catalog: Any) -> None:
    caddy = catalog.get("caddy").template.services["server"]
    assert web.IMAGE == caddy.image_ref


def _vpn_and_nginx(client: Any) -> tuple[int, int]:
    admin(client)
    client.post(f"{API}/zones", json={"name": "Jeux", "color": "#d97706"})
    body = {"template": "wireguard", "name": "vpn", "inputs": {"host": "vpn.example.org"},
            "vpn_zones": ["jeux"]}  # fmt: skip
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    host = nginx_host(client, "Vitrine", 8190)
    moved = client.put(f"{API}/apps/{host}/zone", json={"zone": "jeux"}).json()
    assert wait_job(client, moved["id"])["status"] == "succeeded"
    added = client.post(f"{API}/apps/{host}/sites", json={"name": "Blog", "port": 8081})
    assert added.status_code in (200, 201, 202), added.text
    return deployed["app"]["id"], host


def _wait_web(client: Any) -> None:
    for job in client.get(f"{API}/jobs").json():
        if job["kind"] == "vpn_web":
            assert wait_job(client, job["id"])["status"] == "succeeded"


def test_a_name_on_a_site_goes_through_the_proxy_a_name_on_port_80_does_not(client: Any) -> None:
    vpn_id, host = _vpn_and_nginx(client)
    url = f"{API}/apps/{vpn_id}/vpn/dns"
    target = next(t for t in client.get(url).json()["targets"] if t["id"] == host)
    assert {"service": "server", "port": 80, "protocol": "tcp", "web": True} in target["ports"]
    assert [(s["name"], s["port"], s["main"]) for s in target["sites"]] == [
        ("Vitrine", 80, True), ("Blog", 8081, False)]  # fmt: skip

    blog = client.post(url, json={"name": "blog.lan", "app_id": host, "service": "server",
                                  "port": 8081}).json()["id"]  # fmt: skip
    main = client.post(url, json={"name": "vitrine.lan", "app_id": host, "service": "server",
                                  "port": 80}).json()["id"]  # fmt: skip
    card = client.post(url, json={"name": "plus-tard.lan"}).json()["id"]  # not linked yet
    _wait_web(client)
    records = {r["name"]: r for r in client.get(url).json()["records"]}
    via = {n: (r["via_proxy"], r["url"]) for n, r in records.items()}
    assert via["blog.lan"] == (True, "http://blog.lan")
    assert via["vitrine.lan"] == (False, "http://vitrine.lan")
    assert records["plus-tard.lan"]["app_id"] is None and records["plus-tard.lan"]["url"] is None

    rt = client.app.state.runtime
    proxy = rt.gateway.sidecars[web.NAME]
    assert proxy["image"] == web.IMAGE and list(proxy["networks"]) == ["hivora-zone-jeux"]
    proxy_ip = proxy["networks"]["hivora-zone-jeux"]
    assert proxy_ip.startswith("10.8.1.")  # fixed, in the zone's network (next to the VPN's)
    sites = (rt.settings.data_dir / "web" / "sites.caddy").read_text()
    assert "http://blog.lan {\n    reverse_proxy vitrine-server-1:8081\n}" in sites
    assert "vitrine.lan" not in sites  # port 80: the app's own address
    corefile = (rt.settings.volumes_root / "vpn" / "config" / "coredns" / "Corefile").read_text()
    assert f"        {proxy_ip} blog.lan\n" in corefile
    assert "rewrite continue name exact vitrine.lan. vitrine-server-1. answer auto" in corefile
    view = client.get(f"{API}/addressing").json()
    assert any(
        r["app"] == web.SLUG and r["planned"] == proxy_ip for z in view["zones"] for r in z["rows"]
    )  # shown where the plan is shown

    # Linked to the app itself, then to an IP, then unlinked: the proxy is no longer needed.
    for link in ({"app_id": host}, {"ip": "192.168.1.30"}, {}):
        assert client.put(f"{url}/{blog}", json=link).status_code == 204
    bad = client.put(f"{url}/{blog}", json={"app_id": host, "service": "server", "port": 9})
    assert (bad.status_code, code(bad)) == (409, "vpn_dns_bad_target")
    _wait_web(client)
    assert web.NAME not in rt.gateway.containers  # removed
    assert client.delete(f"{url}/{card}").status_code == 204
    assert client.delete(f"{url}/{main}").status_code == 204


def test_a_removed_app_takes_its_names_and_the_proxy_with_it(client: Any) -> None:
    vpn_id, host = _vpn_and_nginx(client)
    url = f"{API}/apps/{vpn_id}/vpn/dns"
    client.post(url, json={"name": "blog.lan", "app_id": host, "service": "server", "port": 8081})
    _wait_web(client)
    rt = client.app.state.runtime
    assert web.NAME in rt.gateway.containers
    gone = client.delete(f"{API}/apps/{host}").json()
    assert wait_job(client, gone["id"])["status"] == "succeeded"
    import time

    deadline = time.monotonic() + 5
    while web.NAME in rt.gateway.containers:
        assert time.monotonic() < deadline, "the proxy outlived the names it served"
        _wait_web(client)
        time.sleep(0.05)
    assert client.get(url).json()["records"] == []
