"""The /audit routes' behaviour, pinned before their SQL moves into AuditRecorder."""

import time
from typing import Any

from helpers import API, admin

from hivora.audit.models import AuditLog


def _insert(client: Any, count: int) -> None:
    """Known rows written straight to the table (no recorder batching involved)."""
    rt = client.app.state.runtime

    async def insert() -> None:
        async with rt.sessions() as session, session.begin():
            for i in range(count):
                session.add(AuditLog(ts=rt.clock.now(), action=f"test.entry{i}",
                                     payload={"n": i}, result="ok"))  # fmt: skip

    client.portal.call(insert)


def test_audit_list_is_newest_first_with_limit_and_before_id(client: Any) -> None:
    admin(client)
    time.sleep(0.8)  # the recorder writes the login events in small batches
    _insert(client, 5)

    every = client.get(f"{API}/audit").json()
    ids = [a["id"] for a in every]
    assert ids == sorted(ids, reverse=True) and len(ids) == len(set(ids))
    assert [a["action"] for a in every[:5]] == [f"test.entry{i}" for i in (4, 3, 2, 1, 0)]
    assert every[0]["payload"] == {"n": 4} and every[0]["result"] == "ok"

    limited = client.get(f"{API}/audit", params={"limit": 2}).json()
    assert [a["id"] for a in limited] == ids[:2]
    assert client.get(f"{API}/audit", params={"limit": 0}).status_code == 422

    # before_id: only older entries (strictly lower id), still newest first.
    page = client.get(f"{API}/audit", params={"before_id": ids[1], "limit": 2}).json()
    assert [a["id"] for a in page] == ids[2:4]
    older = client.get(f"{API}/audit", params={"before_id": ids[1]}).json()
    assert [a["id"] for a in older] == ids[2:]
    assert client.get(f"{API}/audit", params={"before_id": min(ids)}).json() == []


def test_audit_clear_leaves_one_direct_entry(client: Any) -> None:
    admin(client)
    time.sleep(0.8)
    _insert(client, 3)
    before = client.get(f"{API}/audit", params={"limit": 1000}).json()

    bus = client.app.state.runtime.bus
    published: list[str] = []
    real_publish = bus.publish

    def spy(topic: str, **payload: Any) -> Any:
        published.append(topic)
        return real_publish(topic, **payload)

    bus.publish = spy
    try:
        cleared = client.delete(f"{API}/audit")
        # Read at once, with no wait: the entry is written by the route itself.
        left = client.get(f"{API}/audit").json()
    finally:
        bus.publish = real_publish

    assert cleared.status_code == 200 and cleared.json() == {"deleted": len(before)}
    assert "audit.cleared" not in published  # written directly, not through the bus
    [entry] = left
    assert entry["action"] == "audit.cleared" and entry["payload"] == {"deleted": len(before)}
    assert entry["username"] == "admin" and entry["user_id"] is not None
    assert entry["result"] == "ok"
