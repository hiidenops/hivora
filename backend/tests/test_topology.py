from typing import Any

from helpers import API, admin, wait_job


def by_key(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["key"]: n for n in graph["nodes"]}


def test_topology_graph_declared_layer_and_layout(client: Any) -> None:
    admin(client)
    zones = [{"name": "Jeux", "color": "#d97706", "network_mode": "none"},
             {"name": "Administration2", "color": "#64748b", "network_mode": "shared"}]  # fmt: skip
    for z in zones:
        assert client.post(f"{API}/zones", json=z).status_code == 201

    # Minecraft publishes its game port publicly; Vaultwarden stays on the LAN, without zone.
    def deploy(template: str, name: str, inputs: dict[str, Any], zone: str | None = None) -> Any:
        body = {"template": template, "name": name, "inputs": inputs, "zone": zone}
        return client.post(f"{API}/apps", json=body).json()

    mc = deploy("minecraft", "cube", {"eula": True}, "jeux")
    vw = deploy("vaultwarden", "Coffre", {"web_port": 8090})
    vpn = deploy("wireguard", "vpn", {"host": "vpn.example.org"})
    for d in (mc, vw, vpn):
        assert wait_job(client, d["job"]["id"])["status"] == "succeeded"
    job = client.put(f"{API}/apps/{vpn['app']['id']}/vpn/zones",
                     json={"zones": ["administration2"]}).json()  # fmt: skip
    assert wait_job(client, job["id"])["status"] == "succeeded"

    graph = client.get(f"{API}/topology").json()
    nodes = by_key(graph)
    cube = nodes[f"app:{mc['app']['id']}"]
    assert cube["parent"].startswith("zone:") and nodes[cube["parent"]]["label"] == "Jeux"
    assert any(p["exposure"] == "public" and p["port"] == 25565 for p in cube["ports"])
    assert nodes[f"app:{vw['app']['id']}"]["parent"] == "zone:none"
    assert {"source": "internet", "target": cube["key"], "kind": "exposed",
            "label": "25565/tcp"} in graph["edges"]  # fmt: skip
    vpn_edges = [e for e in graph["edges"] if e["kind"] == "vpn"]
    assert len(vpn_edges) == 1 and nodes[vpn_edges[0]["target"]]["label"] == "Administration2"
    codes = {(a["code"], a.get("app")) for a in graph["alerts"]}
    assert ("public_port", "cube") in codes  # published on every interface
    assert ("no_zone", "Coffre") in codes

    # Declared layer: a firewall linked to the Internet, then positions.
    fw = client.post(f"{API}/topology/nodes", json={"kind": "firewall", "label": "UFW"}).json()
    key = f"decl:{fw['id']}"
    link = {"source": "internet", "target": key, "label": "WAN"}
    edge = client.post(f"{API}/topology/edges", json=link).json()
    bad = client.post(f"{API}/topology/edges", json={"source": "rm -rf", "target": key})
    assert bad.status_code == 422
    layout = {"positions": {key: {"x": 10, "y": 20}, cube["key"]: {"x": 30.5, "y": 40}}}
    assert client.put(f"{API}/topology/layout", json=layout).status_code == 204
    graph = client.get(f"{API}/topology").json()
    assert by_key(graph)[key]["label"] == "UFW"
    assert graph["positions"][key] == {"x": 10, "y": 20, "w": None, "h": None}
    assert any(e.get("id") == edge["id"] for e in graph["edges"])

    client.put(f"{API}/topology/nodes/{fw['id']}", json={"kind": "router", "label": "Box"})
    assert by_key(client.get(f"{API}/topology").json())[key]["kind"] == "router"
    assert client.delete(f"{API}/topology/nodes/{fw['id']}").status_code == 204
    graph = client.get(f"{API}/topology").json()
    assert key not in by_key(graph) and key not in graph["positions"]
    assert not any(e.get("id") == edge["id"] for e in graph["edges"])  # its links went too


def test_declared_layer_edges_layout_errors_and_events(client: Any) -> None:
    """The declared layer's behaviour, pinned before its code moves to a service."""
    from helpers import code

    admin(client)
    bus = client.app.state.runtime.bus
    published: list[tuple[str, dict[str, Any]]] = []
    real_publish = bus.publish

    def spy(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real_publish(topic, **payload)

    bus.publish = spy
    try:
        node = client.post(f"{API}/topology/nodes", json={"kind": "router", "label": "Box"}).json()
        assert ("topology.node_added", {"target": "Box", "kind": "router"}) in published
        key = f"decl:{node['id']}"

        # Links: removing one that exists or not both answer 204.
        edge = client.post(f"{API}/topology/edges",
                           json={"source": "internet", "target": key}).json()  # fmt: skip
        edges = client.get(f"{API}/topology").json()["edges"]
        assert any(e.get("id") == edge["id"] for e in edges)
        assert client.delete(f"{API}/topology/edges/{edge['id']}").status_code == 204
        edges = client.get(f"{API}/topology").json()["edges"]
        assert not any(e.get("id") == edge["id"] for e in edges)
        assert client.delete(f"{API}/topology/edges/999999").status_code == 204

        # Layout: zone sizes kept, keys cut to 40 characters, an empty map resets it.
        long_key = "zone:none" + "x" * 50
        layout = {"positions": {
            "zone:none": {"x": 1, "y": 2, "w": 300, "h": 200},
            long_key: {"x": 5, "y": 6},
        }}  # fmt: skip
        assert client.put(f"{API}/topology/layout", json=layout).status_code == 204
        positions = client.get(f"{API}/topology").json()["positions"]
        assert positions["zone:none"] == {"x": 1, "y": 2, "w": 300, "h": 200}
        assert positions[long_key[:40]] == {"x": 5, "y": 6, "w": None, "h": None}
        assert long_key not in positions
        reset = client.put(f"{API}/topology/layout", json={"positions": {}})
        assert reset.status_code == 204
        assert client.get(f"{API}/topology").json()["positions"] == {}

        # Unknown declared node: 404 topology_node_not_found, to edit or to remove.
        body = {"kind": "note", "label": "?"}
        missing = client.put(f"{API}/topology/nodes/999999", json=body)
        assert missing.status_code == 404 and code(missing) == "topology_node_not_found"
        missing = client.delete(f"{API}/topology/nodes/999999")
        assert missing.status_code == 404 and code(missing) == "topology_node_not_found"
        assert not any(t == "topology.node_removed" for t, _ in published)

        assert client.delete(f"{API}/topology/nodes/{node['id']}").status_code == 204
        assert ("topology.node_removed", {"target": "Box"}) in published
    finally:
        bus.publish = real_publish


def test_put_an_app_behind_the_vpn(client: Any) -> None:
    import yaml
    from helpers import code

    admin(client)
    mc_body = {"template": "minecraft", "name": "cube", "inputs": {"eula": True}}
    vpn_body = {"template": "wireguard", "name": "vpn", "inputs": {"host": "vpn.example.org"}}
    mc = client.post(f"{API}/apps", json=mc_body).json()
    vpn = client.post(f"{API}/apps", json=vpn_body).json()
    for d in (mc, vpn):
        assert wait_job(client, d["job"]["id"])["status"] == "succeeded"
    mc_id, vpn_id = mc["app"]["id"], vpn["app"]["id"]

    # 1. The game port is no longer published (reachable on Docker networks only).
    settings = client.get(f"{API}/apps/{mc_id}/settings").json()
    closed = {"services": {"server": {"publish": {"25565/tcp": "none"}}}}
    change = {"inputs": settings["values"], "overrides": closed}
    assert wait_job(client, client.put(f"{API}/apps/{mc_id}/settings", json=change).json()["id"])[
        "status"] == "succeeded"  # fmt: skip
    compose = yaml.safe_load(client.get(f"{API}/apps/{mc_id}/compose").json()["compose_yaml"])
    server = compose["services"]["server"]
    assert "25565/tcp" in server["expose"] and not any(
        p["target"] == 25565 for p in server.get("ports", [])
    )

    access = client.get(f"{API}/apps/{mc_id}").json()["access"]
    assert "game" not in access and "game_lan" not in access  # no host address any more

    # 2. The VPN joins its network.
    job = client.put(f"{API}/apps/{vpn_id}/vpn/zones", json={"zones": ["@cube"]}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{vpn_id}/compose").json()["compose_yaml"])
    assert compose["networks"]["reach0"] == {"name": "cube_default", "external": True}
    graph = client.get(f"{API}/topology").json()
    assert {"source": f"app:{vpn_id}", "target": f"app:{mc_id}", "kind": "vpn",
            "label": "VPN"} in graph["edges"]  # fmt: skip
    cube = next(n for n in graph["nodes"] if n["key"] == f"app:{mc_id}")
    assert cube["behind_vpn"] is True
    assert not any(e["kind"] == "exposed" and e["target"] == cube["key"] for e in graph["edges"])

    # 3. It cannot be removed while the VPN uses its network; detached, it can.
    refused = client.delete(f"{API}/apps/{mc_id}")
    assert refused.status_code == 409 and "VPN" in refused.json()["error"]["message"]
    assert code(client.put(f"{API}/apps/{vpn_id}/vpn/zones",
                           json={"zones": ["@nope"]})) == "validation_error"  # fmt: skip
    job = client.put(f"{API}/apps/{vpn_id}/vpn/zones", json={"zones": []}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    graph = client.get(f"{API}/topology").json()
    cube = next(n for n in graph["nodes"] if n["key"] == f"app:{mc_id}")
    assert {"override": "none", "default": "public"}.items() <= next(
        p for p in cube["ports"] if p["container"] == 25565
    ).items()
    assert any(a["code"] == "unreachable" and a["app"] == "cube" for a in graph["alerts"])
    assert client.delete(f"{API}/apps/{mc_id}").status_code == 202
