"""DELETE /zones/{slug}: behaviour pinned before its query moves out of the route."""

from typing import Any

from helpers import API, admin, code


def _spy(client: Any) -> tuple[list[str], list[tuple[str, dict[str, Any]]], Any]:
    """Record the Docker networks removed and the events published; returns an undo."""
    rt = client.app.state.runtime
    removed: list[str] = []
    published: list[tuple[str, dict[str, Any]]] = []
    real_remove, real_publish = rt.gateway.remove_network, rt.bus.publish

    async def remove_network(name: str) -> bool:
        removed.append(name)
        result: bool = await real_remove(name)
        return result

    def publish(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real_publish(topic, **payload)

    rt.gateway.remove_network, rt.bus.publish = remove_network, publish

    def undo() -> None:
        rt.gateway.remove_network, rt.bus.publish = real_remove, real_publish

    return removed, published, undo


def test_deleting_an_unknown_zone_touches_nothing(client: Any) -> None:
    admin(client)
    removed, published, undo = _spy(client)
    try:
        missing = client.delete(f"{API}/zones/no-such-zone")
    finally:
        undo()
    assert missing.status_code == 404 and code(missing) == "zone_not_found"
    assert missing.json()["error"]["message"] == "no-such-zone"
    assert removed == []  # no attempt to remove a Docker network
    assert not any(topic == "zone.deleted" for topic, _ in published)


def test_deleting_an_empty_zone_removes_its_network_then_says_so(client: Any) -> None:
    admin(client)
    body = {"name": "Vide", "color": "#64748b", "network_mode": "shared"}
    zone = client.post(f"{API}/zones", json=body).json()
    removed, published, undo = _spy(client)
    try:
        assert client.delete(f"{API}/zones/{zone['slug']}").status_code == 204
    finally:
        undo()
    assert removed == [f"hivora-zone-{zone['slug']}"]
    assert ("zone.deleted", {"target": zone["slug"]}) in published
    assert zone["slug"] not in [z["slug"] for z in client.get(f"{API}/zones").json()]
