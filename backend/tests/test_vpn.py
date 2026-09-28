from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

from hivora.vpn.wgeasy import POST_UP, UPDATE_FIELDS, WgEasy


async def test_wg_easy_client_calls() -> None:
    clients: dict[int, dict[str, Any]] = {}
    seen: list[tuple[str, str, Any]] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        assert request.headers["Authorization"].startswith("Basic ")
        body = await request.json() if request.can_read_body else {}
        seen.append((request.method, request.path, body))
        path = request.path.removeprefix("/api")
        if path == "/client" and request.method == "POST":
            cid = len(clients) + 1
            clients[cid] = {"id": cid, "name": body["name"], "enabled": True, "allowedIps": None}
            clients[cid] |= {"ipv4Address": f"10.8.0.{cid + 1}", "publicKey": f"key{cid}"}
            return web.json_response({"success": True, "clientId": cid})
        if path == "/client":
            return web.json_response(list(clients.values()))
        if path.startswith("/client/"):
            cid = int(path.split("/")[2])
            if cid not in clients:
                return web.json_response({}, status=404)
            if request.method == "DELETE":
                del clients[cid]
            elif request.method == "POST" and path.endswith(str(cid)):
                clients[cid] |= body or {}
            return web.json_response(clients.get(cid, {}))
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    async with TestServer(app) as server:
        api = WgEasy(str(server.make_url("/")), "admin", "pw")
        cid = await api.create("phone")
        await api.update(cid, allowedIps=["192.168.1.0/24"])
        full = seen[-1][2]
        assert full["name"] == "phone" and full["allowedIps"] == ["192.168.1.0/24"]  # whole object
        assert set(UPDATE_FIELDS) <= set(full)  # wg-easy rejects a partial client
        assert (await api.clients())[0]["allowedIps"] == ["192.168.1.0/24"]
        await api.nat_all_interfaces()
        assert seen[-1][1] == "/api/admin/hooks" and seen[-1][2]["postUp"] == POST_UP
        assert "-s {{ipv4Cidr}} -j MASQUERADE" in POST_UP  # every interface, zone networks too


def test_vpn_reaches_linked_zones_only(client: Any) -> None:
    import yaml
    from helpers import API, admin, code, wait_job

    admin(client)
    client.post(f"{API}/zones", json={"name": "Jeux", "color": "#d97706", "network_mode": "shared"})
    client.post(f"{API}/zones", json={"name": "Solo", "color": "#65a30d"})
    inputs = {"host": "vpn.example.org", "admin_password": "correct-horse-12"}
    body = {"template": "wireguard", "name": "vpn", "inputs": inputs}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    assert client.get(f"{API}/apps/{app_id}").json()["vpn"] is True

    job = client.put(f"{API}/apps/{app_id}/vpn/zones", json={"zones": ["jeux"]}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    assert compose["networks"]["reach0"] == {"name": "hivora-zone-jeux", "external": True}
    assert client.get(f"{API}/apps/{app_id}/vpn").json()["zones"] == ["jeux"]

    refused = client.put(f"{API}/apps/{app_id}/vpn/zones", json={"zones": ["solo"]})
    assert refused.status_code == 422
    stopped = client.post(f"{API}/apps/{app_id}/vpn/clients", json={"name": "phone"})
    assert stopped.status_code == 409 and code(stopped) == "vpn_not_running"
